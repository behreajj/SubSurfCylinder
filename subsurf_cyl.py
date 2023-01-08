import bpy
import bmesh
import math
import mathutils
from bpy.props import (
    BoolProperty,
    IntProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty)


bl_info = {
    "name": "Create Tube",
    "author": "Jeremy Behreandt",
    "version": (0, 1),
    "blender": (3, 3, 1),
    "category": "Add Mesh",
    "description": "Creates a tube.",
    "tracker_url": "https://github.com/behreajj/"
}


class TubeMaker(bpy.types.Operator):
    """Creates a tube"""

    bl_idname = "mesh.primitive_tube_add"
    bl_label = "Tube"
    bl_options = {"REGISTER", "UNDO"}


    sectors: IntProperty(
        name="Vertices",
        description="Number of vertices on the tube circumference",
        min=3,
        soft_max=64,
        default=8)

    orientation: FloatProperty(
        name="Rotation",
        description="Rotation of the tube",
        soft_min=-math.pi,
        soft_max=math.pi,
        default=0.0,
        subtype="ANGLE",
        unit="ROTATION")

    radius_btm: FloatProperty(
        name="Bottom Radius",
        description="Tube radius at the bottom",
        min=0.001,
        soft_max=100.0,
        default=0.5)

    radius_top: FloatProperty(
        name="Top Radius",
        description="Tube radius at the top",
        min=0.001,
        soft_max=100.0,
        default=0.5)

    depth: FloatProperty(
        name="Depth",
        description="Tube depth",
        min=0.001,
        soft_max=100.0,
        default=1.5)

    depth_offset: FloatProperty(
        name="Offset",
        description="Offset on the z axis",
        default=0.0,
        step=1,
        precision=3,
        min=-1.0,
        max=1.0,
        subtype="FACTOR")

    cap_face_type: EnumProperty(
        items=[
            ("NGON", "NGon", "Use n-sides polygons", 1),
            ("QUAD", "Quad", "Use quadrilaterals for an even number of vertices", 2),
            ("TRI", "Tri", "Use triangles", 3),
            ("NONE", "None", "Do not add end caps", 4)
        ],
        name="Cap Fill Type",
        default="QUAD",
        description="How to create end cap polygons"
    )

    edge_loop_fac: FloatProperty(
        name="Edge Loops",
        description="Add loops used to control a subdivision surface modifier.",
        default=0.0,
        step=1,
        precision=3,
        min=0.0,
        max=1.0,
        subtype="FACTOR")

    shade_smooth: BoolProperty(
        name="Shade Smooth",
        description="Whether to use smooth shading",
        default=True)

    auto_normals: BoolProperty(
        name="Auto Smooth",
        description="Auto smooth (based on smooth/sharp faces/edges and angle between faces)",
        default=True)

    auto_angle: FloatProperty(
        name="Auto Smooth Angle",
        description="Maximum angle between face normals that will be considered as smooth",
        subtype="ANGLE",
        min=0.0,
        max=3.14159,
        step=100,
        default=0.523599)

    calc_uvs: BoolProperty(
        name="Calc UVs",
        description="Calculate texture coordinates",
        default=False)

    def execute(self, context):
        # TODO: Add options to mark seams if UV coordinates are calculated?

        # Unpack arguments.
        sectors = self.sectors
        orientation = self.orientation
        radius_btm = self.radius_btm
        radius_top = self.radius_top
        depth = self.depth
        depth_offset = self.depth_offset
        cap_face_type = self.cap_face_type
        edge_loop_fac = self.edge_loop_fac
        shade_smooth = self.shade_smooth
        auto_normals = self.auto_normals
        auto_angle = self.auto_angle
        calc_uvs = self.calc_uvs

        # Convert string comparisons of cap face type
        # to booleans.
        cap_is_none = cap_face_type == "NONE"
        cap_is_ngon = cap_face_type == "NGON"
        cap_is_quad = cap_face_type == "QUAD"
        cap_is_tri = cap_face_type == "TRI"

        # A quadrilateral based end cap is possible only
        # when the number of sectors or vertices is even.
        # If not, then default to an n-gon face.
        if (sectors < 5) or (sectors % 2 != 0):
            cap_is_quad = False
            if not cap_is_none:
                cap_is_ngon = True

        if sectors < 4:
            cap_is_tri = False
            if not cap_is_none:
                cap_is_ngon = True

        # Derive some booleans from combinations of the above.
        # Used in deciding index offsets for vertices and faces.
        use_center_spoke = cap_is_tri or cap_is_quad
        use_caps = cap_is_tri or cap_is_quad or cap_is_ngon
        use_edge_loops = edge_loop_fac > 0.0 \
                     and edge_loop_fac < 1.0

        # Convert offset from [-1.0, 1.0] to [0.0, 1.0],
        # Use it as a factor to find the cylinder's middle
        # on the z axis. Then find the top and bottom.
        offset_fac = depth_offset * 0.5 + 0.5
        half_depth = depth * 0.5
        vz_mid = (1.0 - offset_fac) * -half_depth \
                      + offset_fac * half_depth
        vz_btm = vz_mid - half_depth
        vz_top = vz_mid + half_depth

        # Alias edge loop factor to make linear interpolation
        # easier.
        t = edge_loop_fac
        u = 1.0 - t

        # To make the rounding of a Catmull Subsurf modifier
        # more uniform, the factors used to set control loops
        # need to be scaled according to whether depth is
        # greater than radius or vice versa.
        aspect_ratio_btm = 1.0
        aspect_ratio_top = 1.0
        if use_caps:
            aspect_ratio_btm = radius_btm / depth
            aspect_ratio_top = radius_top / depth

        # For control loops on side panels.
        t_btm = t
        u_btm = u
        if radius_btm < depth:
            t_btm = t * aspect_ratio_btm
            u_btm = 1.0 - t_btm

        t_top = t
        u_top = u
        if radius_top < depth:
            t_top = t * aspect_ratio_top
            u_top = 1.0 - t_top

        # For control loops on end caps.
        t_fan_btm = t
        u_fan_btm = u
        if radius_btm >= depth:
            t_fan_btm = t / aspect_ratio_btm
            u_fan_btm = 1.0 - t_fan_btm

        t_fan_top = t
        u_fan_top = u
        if radius_top >= depth:
            t_fan_top = t / aspect_ratio_top
            u_fan_top = 1.0 - t_fan_top

        # Cache the sine and cosine calculations for
        # the cylinder's radius, as they will be re-used.
        sectors_to_theta = math.tau / sectors
        cartesian = [(0.0, 0.0)] * sectors
        sectors_range = range(0, sectors)
        for i in sectors_range:
            theta = orientation + i * sectors_to_theta
            cos_t = math.cos(theta)
            sin_t = math.sin(theta)
            cartesian[i] = (cos_t, sin_t)

        # Find index offsets for vector3s in vertices
        # array. Ideally, vertices should be in order from
        # z negative to z positive.
        v_idx_btm_spoke = 0
        v_idx_btm_fan = v_idx_btm_spoke
        if use_center_spoke:
            v_idx_btm_fan += 1
        v_idx_btm_ctrl = v_idx_btm_fan
        if use_edge_loops and use_caps:
            v_idx_btm_ctrl += sectors
        v_idx_btm_edge = v_idx_btm_ctrl
        if use_edge_loops and use_caps:
            v_idx_btm_edge += sectors
        v_idx_side_lwr_ctrl = v_idx_btm_edge + sectors
        v_idx_mid = v_idx_side_lwr_ctrl
        if use_edge_loops:
            v_idx_mid += sectors
        v_idx_side_upp_ctrl = v_idx_mid
        if use_edge_loops:
            v_idx_side_upp_ctrl += sectors
        v_idx_top_edge = v_idx_side_upp_ctrl
        if use_edge_loops:
            v_idx_top_edge += sectors
        v_idx_top_ctrl = v_idx_top_edge
        if use_edge_loops:
            v_idx_top_ctrl += sectors
        v_idx_top_fan = v_idx_top_ctrl
        if use_edge_loops:
            v_idx_top_fan += sectors
        v_idx_top_spoke = v_idx_top_fan
        if use_caps or cap_is_none:
            v_idx_top_spoke += sectors

        # Total length of vertices is the found at
        # the end by summing all index offsets.
        len_vs = v_idx_top_spoke
        if use_center_spoke:
            len_vs += 1
        vs = [(0.0, 0.0, 0.0)] * len_vs

        # For quads and tris, create a central spoke.
        if use_center_spoke:
            vs[v_idx_btm_spoke] = (0.0, 0.0, vz_btm)
            vs[v_idx_top_spoke] = (0.0, 0.0, vz_top)

        # Calculate top and bottom cylinder rings.
        for i in sectors_range:
            cart = cartesian[i]
            cos_t = cart[0]
            sin_t = cart[1]

            vs[v_idx_btm_edge + i] = (
                cos_t * radius_btm,
                sin_t * radius_btm,
                vz_btm)

            vs[v_idx_top_edge + i] = (
                cos_t * radius_top,
                sin_t * radius_top,
                vz_top)

        if use_edge_loops:
            radius_mid = (radius_btm + radius_top) * 0.5

            side_lwr_ctrl_z = u_btm * vz_btm + t_btm * vz_mid
            side_upp_ctrl_z = u_top * vz_top + t_top * vz_mid

            radius_side_lwr_ctrl = u_btm * radius_btm + t_btm * radius_mid
            radius_side_upp_ctrl = u_top * radius_top + t_top * radius_mid

            # Find the middle ring, lower and upper control
            # loops on the side of the cylinder.
            for i in sectors_range:
                cart = cartesian[i]
                cos_t = cart[0]
                sin_t = cart[1]

                vs[v_idx_side_lwr_ctrl + i] = (
                    cos_t * radius_side_lwr_ctrl,
                    sin_t * radius_side_lwr_ctrl,
                    side_lwr_ctrl_z)

                vs[v_idx_mid + i] = (
                    cos_t * radius_mid,
                    sin_t * radius_mid,
                    vz_mid)

                vs[v_idx_side_upp_ctrl + i] = (
                    cos_t * radius_side_upp_ctrl,
                    sin_t * radius_side_upp_ctrl,
                    side_upp_ctrl_z)

            if use_caps:
                radius_fan_btm = radius_btm * 0.5
                radius_cap_lwr_ctrl = u_fan_btm * radius_btm \
                                    + t_fan_btm * radius_fan_btm

                radius_fan_top = radius_top * 0.5
                radius_cap_upp_ctrl = u_fan_top * radius_top \
                                    + t_fan_top * radius_fan_top

                # If end caps are used, find the middle fan
                # and the control loop for both top and bottom.
                for i in sectors_range:
                    cart = cartesian[i]
                    cos_t = cart[0]
                    sin_t = cart[1]

                    vs[v_idx_btm_fan + i] = (
                        cos_t * radius_fan_btm,
                        sin_t * radius_fan_btm,
                        vz_btm)

                    vs[v_idx_btm_ctrl + i] = (
                        cos_t * radius_cap_lwr_ctrl,
                        sin_t * radius_cap_lwr_ctrl,
                        vz_btm)

                    vs[v_idx_top_ctrl + i] = (
                        cos_t * radius_cap_upp_ctrl,
                        sin_t * radius_cap_upp_ctrl,
                        vz_top)

                    vs[v_idx_top_fan + i] = (
                        cos_t * radius_fan_top,
                        sin_t * radius_fan_top,
                        vz_top)

        # For quad faces, a fan consists of half the number
        # of sectors as triangle faces.
        half_sectors = sectors // 2
        half_sectors_range = range(0, half_sectors)

        # Loop array offsets and length are equivalent
        # for all mesh data -- coordinates (vs), texture
        # coordinates (vts) and normals (vns).
        loop_idx_btm_fan = 0
        loop_idx_btm_mid = loop_idx_btm_fan
        if cap_is_ngon:
            loop_idx_btm_mid += 1
        elif cap_is_quad:
            loop_idx_btm_mid += half_sectors
        elif cap_is_tri:
            loop_idx_btm_mid += sectors

        loop_idx_btm_ctrl = loop_idx_btm_mid
        if use_edge_loops and use_caps:
            loop_idx_btm_ctrl += sectors

        loop_idx_side_lwr_ctrl = loop_idx_btm_ctrl
        if use_edge_loops and use_caps:
            loop_idx_side_lwr_ctrl += sectors

        loop_idx_side_lwr = loop_idx_side_lwr_ctrl
        if use_edge_loops:
            loop_idx_side_lwr += sectors

        loop_idx_side_upp = loop_idx_side_lwr
        if use_edge_loops:
            loop_idx_side_upp += sectors

        loop_idx_side_upp_ctrl = loop_idx_side_upp
        if use_edge_loops:
            loop_idx_side_upp_ctrl += sectors

        loop_idx_top_ctrl = loop_idx_side_upp_ctrl
        if use_edge_loops and use_caps:
            loop_idx_top_ctrl += sectors

        loop_idx_top_mid = loop_idx_top_ctrl
        if use_edge_loops and use_caps:
            loop_idx_top_mid += sectors

        loop_idx_top_fan = loop_idx_top_mid + sectors
   
        len_loop_idcs = loop_idx_top_fan
        if cap_is_ngon:
            len_loop_idcs += 1
        elif cap_is_quad:
            len_loop_idcs += half_sectors
        elif cap_is_tri:
            len_loop_idcs += sectors

        v_idcs = [(0, 0, 0, 0)] * len_loop_idcs

        # Create central fan.
        if cap_is_tri:
            for i in sectors_range:
                j = (i + 1) % sectors
                v_idcs[loop_idx_btm_fan + i] = (
                    v_idx_btm_spoke,
                    v_idx_btm_fan + j,
                    v_idx_btm_fan + i)
                v_idcs[loop_idx_top_fan + i] = (
                    v_idx_top_spoke,
                    v_idx_top_fan + i,
                    v_idx_top_fan + j)
        elif cap_is_quad:
            for h in half_sectors_range:
                i = h + h
                j = (i + 1) % sectors
                k = (i + 2) % sectors
                v_idcs[loop_idx_btm_fan + h] = (
                    v_idx_btm_spoke,
                    v_idx_btm_fan + k,
                    v_idx_btm_fan + j,
                    v_idx_btm_fan + i)
                v_idcs[loop_idx_top_fan + h] = (
                    v_idx_top_spoke,
                    v_idx_top_fan + i,
                    v_idx_top_fan + j,
                    v_idx_top_fan + k)
        elif cap_is_ngon:
            idcs_btm_arr = [0] * sectors
            idcs_top_arr = [0] * sectors
            for i in sectors_range:
                j = (i - 1) % sectors
                idcs_btm_arr[i] = v_idx_btm_fan + sectors - 1 - j
                idcs_top_arr[i] = v_idx_top_fan + i
            v_idcs[loop_idx_btm_fan] = tuple(idcs_btm_arr)
            v_idcs[loop_idx_top_fan] = tuple(idcs_top_arr)

        if use_edge_loops:
            if use_caps:
                for i in sectors_range:
                    j = (i + 1) % sectors

                    v_idcs[loop_idx_btm_mid + i] = (
                        v_idx_btm_fan + i,
                        v_idx_btm_fan + j,
                        v_idx_btm_ctrl + j,
                        v_idx_btm_ctrl + i)

                    v_idcs[loop_idx_btm_ctrl + i] = (
                        v_idx_btm_ctrl + i,
                        v_idx_btm_ctrl + j,
                        v_idx_btm_edge + j,
                        v_idx_btm_edge + i)
                    
                    v_idcs[loop_idx_top_ctrl + i] = (
                        v_idx_top_edge + i,
                        v_idx_top_edge + j,
                        v_idx_top_ctrl + j,
                        v_idx_top_ctrl + i)

                    v_idcs[loop_idx_top_mid + i] = (
                        v_idx_top_ctrl + i,
                        v_idx_top_ctrl + j,
                        v_idx_top_fan + j,
                        v_idx_top_fan + i)

            # Create side panel faces.
            for i in sectors_range:
                j = i + 1
                k = j % sectors

                v_idcs[loop_idx_side_lwr_ctrl + i] = (
                    v_idx_btm_edge + i,
                    v_idx_btm_edge + k,
                    v_idx_side_lwr_ctrl + k,
                    v_idx_side_lwr_ctrl + i)

                v_idcs[loop_idx_side_lwr + i] = (
                    v_idx_side_lwr_ctrl + i,
                    v_idx_side_lwr_ctrl + k,
                    v_idx_mid + k,
                    v_idx_mid + i)

                v_idcs[loop_idx_side_upp + i] = (
                    v_idx_mid + i,
                    v_idx_mid + k,
                    v_idx_side_upp_ctrl + k,
                    v_idx_side_upp_ctrl + i)

                v_idcs[loop_idx_side_upp_ctrl + i] = (
                    v_idx_side_upp_ctrl + i,
                    v_idx_side_upp_ctrl + k,
                    v_idx_top_edge + k,
                    v_idx_top_edge + i)
        else:
            for i in sectors_range:
                j = i + 1
                k = j % sectors

                v_idcs[loop_idx_side_lwr_ctrl + i] = (
                    v_idx_btm_edge + i,
                    v_idx_btm_edge + k,
                    v_idx_top_edge + k,
                    v_idx_top_edge + i)

        d_objs = bpy.data.objects
        d_meshes = bpy.data.meshes
        scene_objs = context.scene.collection.objects

        mesh_data = d_meshes.new("Cylinder")
        mesh_data.from_pydata(vs, [], v_idcs)
        mesh_data.validate(verbose=True)
        mesh_data.use_auto_smooth = auto_normals
        mesh_data.auto_smooth_angle = auto_angle

        bm = bmesh.new()
        bm.from_mesh(mesh_data)

        for face in bm.faces:
            face.smooth = shade_smooth

        if calc_uvs:

            # Order of vts matters less than of coordinates
            # or of faces, so indexed offsets are calculated
            # according to convenience.
            sectorsp1 = sectors + 1
            len_vts = sectorsp1 * 2
            if use_edge_loops:
                len_vts += sectorsp1 * 3
            if use_caps:
                len_vts += sectors * 2
                if use_edge_loops:
                    len_vts += sectors * 4
                if use_center_spoke:
                    len_vts += 2

            vt_idx_btm_strip = 0
            vt_idx_top_strip = sectorsp1

            vt_idx_side_lwr_ctrl = -1
            vt_idx_mid_strip = -1
            vt_idx_side_upp_ctrl = -1
            if use_edge_loops:
                vt_idx_side_lwr_ctrl = sectorsp1 * 2
                vt_idx_mid_strip = sectorsp1 * 3
                vt_idx_side_upp_ctrl = sectorsp1 * 4

            vt_idx_btm_edge = -1
            vt_idx_btm_ctrl = -1
            vt_idx_btm_fan = -1
            vt_idx_top_edge = -1
            vt_idx_top_ctrl = -1
            vt_idx_top_fan = -1
            vt_idx_btm_spoke = -1
            vt_idx_top_spoke = -1

            if use_caps:
                sectorsp1_2 = sectorsp1 * 2
                vt_idx_btm_edge = sectorsp1_2
                vt_idx_top_edge = sectorsp1_2 + sectors

                # In case no edge loops are used, the edge
                # and the fan will be the same index offsets.
                vt_idx_btm_fan = vt_idx_btm_edge
                vt_idx_top_fan = vt_idx_top_edge

                if use_edge_loops:
                    sectorsp1_5 = sectorsp1 * 5
                    vt_idx_btm_edge = sectorsp1_5
                    vt_idx_btm_ctrl = sectorsp1_5 + sectors
                    vt_idx_btm_fan = sectorsp1_5 + sectors * 2

                    vt_idx_top_edge = sectorsp1_5 + sectors * 3
                    vt_idx_top_ctrl = sectorsp1_5 + sectors * 4
                    vt_idx_top_fan =  sectorsp1_5 + sectors * 5

                if use_center_spoke:
                    vt_idx_btm_spoke = len_vts - 2
                    vt_idx_top_spoke = len_vts - 1
            
            vts = [(0.0, 0.0)] * len_vts

            # If no end caps are used, then the cylinder sides
            # span the entire UV range. Otherwise, the sides
            # are compressed to the top-half of the range and
            # the end caps are on the bottom-half.
            vts_min_y = 0.0
            if use_caps:
                vts_min_y = 0.5
            vts_max_y = 1.0

            # Find the top and bottom of the uv sides.
            # UVs include one extra edge, as the wrapping
            # at (0.0, 1.0) is automatically calculated.
            sectorsp1_range = range(0, sectorsp1)
            sectors_to_uv = 1.0 / sectors
            for j in sectorsp1_range:
                x = j * sectors_to_uv
                vts[vt_idx_btm_strip + j] = (x, vts_min_y)
                vts[vt_idx_top_strip + j] = (x, vts_max_y)

            if use_edge_loops:
                vts_mid_y = (vts_min_y + vts_max_y) * 0.5
                vt_side_lwr_ctrl_y = u_btm * vts_min_y + t_btm * vts_mid_y
                vt_side_upp_ctrl_y = u_top * vts_max_y + t_top * vts_mid_y

                for j in sectorsp1_range:
                    x = j * sectors_to_uv
                    vts[vt_idx_side_lwr_ctrl + j] = (x, vt_side_lwr_ctrl_y)
                    vts[vt_idx_mid_strip + j] = (x, vts_mid_y)
                    vts[vt_idx_side_upp_ctrl + j] = (x, vt_side_upp_ctrl_y)

            if use_caps:
                vts_rad = 0.25

                # Follows Blender UV conventions.
                vt_btm_center_x = 0.75
                vt_btm_center_y = 0.25

                vt_top_center_x = 0.25
                vt_top_center_y = 0.25

                # For fan-based end caps, add the central spoke.
                if use_center_spoke:
                    vts[vt_idx_btm_spoke] = (
                        vt_btm_center_x,
                        vt_btm_center_y)
                    vts[vt_idx_top_spoke] = (
                        vt_top_center_x,
                        vt_top_center_y)

                for i in sectors_range:
                    cart = cartesian[i]
                    cos_t = cart[0]
                    sin_t = cart[1]

                    vts[vt_idx_btm_edge + i] = (
                        vt_btm_center_x + cos_t * vts_rad,
                        vt_btm_center_y + sin_t * vts_rad)

                    vts[vt_idx_top_edge + i] = (
                        vt_top_center_x + cos_t * vts_rad,
                        vt_top_center_y + sin_t * vts_rad)

                if use_edge_loops:
                    vts_radius_mid = vts_rad * 0.5
                    vts_radius_cap_lwr_ctrl = u_fan_btm * vts_rad \
                                            + t_fan_btm * vts_radius_mid
                    vts_radius_cap_upp_ctrl = u_fan_top * vts_rad \
                                            + t_fan_top * vts_radius_mid

                    for i in sectors_range:
                        cart = cartesian[i]
                        cos_t = cart[0]
                        sin_t = cart[1]

                        cos_t_mid = cos_t * vts_radius_mid
                        sin_t_mid = sin_t * vts_radius_mid

                        vts[vt_idx_btm_fan + i] = (
                            vt_btm_center_x + cos_t_mid,
                            vt_btm_center_y + sin_t_mid)

                        vts[vt_idx_btm_ctrl + i] = (
                            vt_btm_center_x + cos_t * vts_radius_cap_lwr_ctrl,
                            vt_btm_center_y + sin_t * vts_radius_cap_lwr_ctrl)

                        vts[vt_idx_top_ctrl + i] = (
                            vt_top_center_x + cos_t * vts_radius_cap_upp_ctrl,
                            vt_top_center_y + sin_t * vts_radius_cap_upp_ctrl)

                        vts[vt_idx_top_fan + i] = (
                            vt_top_center_x + cos_t_mid,
                            vt_top_center_y + sin_t_mid)

            # Loop indices are consistent across all data types.
            vt_idcs = [(0, 0, 0, 0)] * len_loop_idcs

            if cap_is_tri:
                for i in sectors_range:
                    j = (i + 1) % sectors
                    vt_idcs[loop_idx_btm_fan + i] = (
                        vt_idx_btm_spoke,
                        vt_idx_btm_fan + j,
                        vt_idx_btm_fan + i)
                    vt_idcs[loop_idx_top_fan + i] = (
                        vt_idx_top_spoke, 
                        vt_idx_top_fan + i,
                        vt_idx_top_fan + j)
            elif cap_is_quad:
                for h in half_sectors_range:
                    i = h + h
                    j = (i + 1) % sectors
                    k = (i + 2) % sectors
                    vt_idcs[loop_idx_btm_fan + h] = (
                        vt_idx_btm_spoke,
                        vt_idx_btm_fan + k,
                        vt_idx_btm_fan + j,
                        vt_idx_btm_fan + i)
                    vt_idcs[loop_idx_top_fan + h] = (
                        vt_idx_top_spoke,
                        vt_idx_top_fan + i,
                        vt_idx_top_fan + j,
                        vt_idx_top_fan + k)
            elif cap_is_ngon:
                idcs_btm_arr = [0] * sectors
                idcs_top_arr = [0] * sectors
                for i in sectors_range:
                    j = (i - 1) % sectors
                    idcs_btm_arr[i] = vt_idx_btm_fan + sectors - 1 - j
                    idcs_top_arr[i] = vt_idx_top_fan + i
                vt_idcs[loop_idx_btm_fan] = tuple(idcs_btm_arr)
                vt_idcs[loop_idx_top_fan] = tuple(idcs_top_arr)

            if use_edge_loops:
                if use_caps:
                    for i in sectors_range:
                        j = (i + 1) % sectors
                        vt_idcs[loop_idx_btm_mid + i] = (
                            vt_idx_btm_fan + i,
                            vt_idx_btm_fan + j,
                            vt_idx_btm_ctrl + j,
                            vt_idx_btm_ctrl + i)
                        vt_idcs[loop_idx_btm_ctrl + i] = (
                            vt_idx_btm_ctrl + i,
                            vt_idx_btm_ctrl + j,
                            vt_idx_btm_edge + j,
                            vt_idx_btm_edge + i)
                        vt_idcs[loop_idx_top_ctrl + i] = (
                            vt_idx_top_edge + i,
                            vt_idx_top_edge + j,
                            vt_idx_top_ctrl + j,
                            vt_idx_top_ctrl + i)
                        vt_idcs[loop_idx_top_mid + i] = (
                            vt_idx_top_ctrl + i,
                            vt_idx_top_ctrl + j,
                            vt_idx_top_fan + j,
                            vt_idx_top_fan + i)
                    
                # Create side panels.
                for i in sectors_range:
                    j = i + 1
                    vt_idcs[loop_idx_side_lwr_ctrl + i] = (
                        vt_idx_btm_strip + i,
                        vt_idx_btm_strip + j,
                        vt_idx_side_lwr_ctrl + j,
                        vt_idx_side_lwr_ctrl + i)
                    vt_idcs[loop_idx_side_lwr + i] = (
                        vt_idx_side_lwr_ctrl + i,
                        vt_idx_side_lwr_ctrl + j,
                        vt_idx_mid_strip + j,
                        vt_idx_mid_strip + i)
                    vt_idcs[loop_idx_side_upp + i] = (
                        vt_idx_mid_strip + i,
                        vt_idx_mid_strip + j,
                        vt_idx_side_upp_ctrl + j,
                        vt_idx_side_upp_ctrl + i)
                    vt_idcs[loop_idx_side_upp_ctrl + i] = (
                        vt_idx_side_upp_ctrl + i,
                        vt_idx_side_upp_ctrl + j,
                        vt_idx_top_strip + j,
                        vt_idx_top_strip + i)
            else:
                for i in sectors_range:
                    j = i + 1
                    vt_idcs[loop_idx_side_lwr_ctrl + i] = (
                        vt_idx_btm_strip + i,
                        vt_idx_btm_strip + j,
                        vt_idx_top_strip + j,
                        vt_idx_top_strip + i)

            uv_layer = bm.loops.layers.uv.verify()
            for face in bm.faces:
                face.smooth = shade_smooth
                faceuvidcs = vt_idcs[face.index]
                for i, loop in enumerate(face.loops):
                    loop[uv_layer].uv = vts[faceuvidcs[i]]

        bm.to_mesh(mesh_data)
        bm.free()

        mesh_obj = d_objs.new(mesh_data.name, mesh_data)
        mesh_obj.location = context.scene.cursor.location
        scene_objs.link(mesh_obj)

        return {"FINISHED"}

    @classmethod
    def poll(cls, context):
        return context.area.type == "VIEW_3D"

def menu_func(self, context):
    self.layout.operator(TubeMaker.bl_idname, icon="MESH_CYLINDER")


def register():
    bpy.utils.register_class(TubeMaker)
    bpy.types.VIEW3D_MT_mesh_add.append(menu_func)


def unregister():
    bpy.utils.unregister_class(TubeMaker)
    bpy.types.VIEW3D_MT_mesh_add.remove(menu_func)
