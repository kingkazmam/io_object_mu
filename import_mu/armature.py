# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

import bpy
from mathutils import Vector, Quaternion, Matrix
from ..utils import create_data_object

BONE_LENGTH = 0.1
#matrix for converting between LHS and RHS (works either direction)
Matrix_YZ = Matrix(((1,0,0,0),
                    (0,0,1,0),
                    (0,1,0,0),
                    (0,0,0,1)))

def create_vertex_groups(obj, bones, weights):
    mesh = obj.data
    for bone in bones:
        obj.vertex_groups.new(name=bone)
    for vind, weight in enumerate(weights):
        for i in range(4):
            bind, bweight = weight.indices[i], weight.weights[i]
            if bweight != 0:
                obj.vertex_groups[bind].add((vind,), bweight, 'ADD')

def create_armature_modifier(obj, armobj):
    def add_modifier(obj, name, armature):
        mod = obj.modifiers.new(name=name, type='ARMATURE')
        mod.use_apply_on_spline = False
        mod.use_bone_envelopes = False
        mod.use_deform_preserve_volume = False # silly Unity :P
        mod.use_multi_modifier = False
        mod.use_vertex_groups = True
        mod.object = armature
    add_modifier(obj, "BindPose", armobj.bindPose_obj)
    add_modifier(obj, "Armature", armobj.armature_obj)

def parent_to_bone(child, armature, bone):
    child.parent = armature
    child.parent_type = 'BONE'
    child.parent_bone = bone
    child.matrix_parent_inverse[1][3] = -BONE_LENGTH

def create_bone(bone_obj, edit_bones):
    xform = bone_obj.transform
    bone = edit_bones.new(xform.name)
    # actual positions and orientations will be sorted out when building
    # the hierarchy
    bone.head = Vector((0, 0, 0))
    bone.tail = bone.head + Vector((0, BONE_LENGTH, 0))
    bone.use_connect = False
    bone.use_inherit_rotation = True
    bone.use_envelope_multiply = False
    bone.use_deform = True
    bone.use_inherit_scale = True
    bone.use_local_location = False
    bone.use_relative_parent = False
    bone.use_cyclic_offset = False
    return bone

def process_armature(armobj, rootBones):
    def process_bone(obj, position, rotation):
        obj.bone.head = rotation @ Vector(obj.position) + position
        rot = Quaternion(obj.rotation)
        lrot = rotation @ rot
        y = BONE_LENGTH
        obj.bone.tail = obj.bone.head + lrot @ Vector((0, y, 0))
        obj.bone.align_roll(lrot @ Vector((0, 0, 1)))
        for child in obj.children:
            if hasattr(child, "armature") and child.armature == armobj:
                process_bone(child, obj.bone.head, lrot)
        # must not keep references to bones when the armature leaves edit mode,
        # so keep the bone's name instead (which is what's needed for bone
        # parenting anway)
        obj.bone = obj.bone.name

    pos = Vector((0, 0, 0))
    rot = Quaternion((1, 0, 0, 0))
    #the armature object has no bone
    for rootBone in rootBones:
        process_bone(rootBone, pos, rot)

def find_bones(mu, skin, siblings):
    bone_names = set(skin.skinned_mesh_renderer.bones)
    for i, bname in enumerate(skin.skinned_mesh_renderer.bones):
        bone = mu.objects[bname]
        bp = skin.skinned_mesh_renderer.mesh.bindPoses[i]
        bp = Matrix((bp[0:4], bp[4:8], bp[8:12], bp[12:16]))
        bone.bindPose = Matrix_YZ @ bp @ Matrix_YZ
    bones = set()
    for bname in bone_names:
        bones.add(mu.objects[bname])

    prev_bones = set()
    while bones - prev_bones:
        prev_bones = bones
        bones = set()
        for b in prev_bones:
            bones.add(b)
            while b not in siblings:
                b = b.parent
                bones.add(b)
    #print(list(map(lambda b: b.transform.name, bones)))

    return bones

def create_armature(mu, skins, siblings):
    #FIXME assumes all skin transfroms and bind poses are compatible
    siblings = set(siblings)
    rootBones = set()
    bones = set()
    for skin in skins:
        bones.update(find_bones(mu, skin, siblings))

    armobj = skins[0]
    armobj.position = Vector(armobj.transform.localPosition)
    armobj.rotation = Quaternion(armobj.transform.localRotation)

    name = armobj.transform.name
    armobj.armature = bpy.data.armatures.new(name)
    armobj.bindPose = bpy.data.armatures.new(name + ".bindPose")
    armobj.armature.show_axes = True
    armobj.bindPose.show_axes = True
    armobj.armature_obj = create_data_object(name, armobj.armature,
                                             armobj.transform)
    armobj.bindPose_obj = create_data_object(name + ".bindPose",
                                             armobj.bindPose, None)
    armobj.bindPose_obj.parent = armobj.armature_obj

    ctx = bpy.context
    # link armature objects so they can be edited
    ctx.layer_collection.collection.objects.link(armobj.armature_obj)
    ctx.layer_collection.collection.objects.link(armobj.bindPose_obj)

    save_active = ctx.view_layer.objects.active
    ctx.view_layer.objects.active = armobj.armature_obj
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    for b in bones:
        b.position = Vector(b.transform.localPosition)
        b.rotation = Quaternion(b.transform.localRotation)
        b.relRotation = Quaternion((1, 0, 0, 0))
        if b in siblings:
            r = armobj.rotation.inverted()
            b.rotation = r @ b.rotation
            b.position = r @ (b.position - armobj.position)
            b.relRotation = r
        b.armature = armobj
        b.bone = create_bone(b, armobj.armature.edit_bones)
    for b in bones:
        if b.parent in bones:
            b.bone.parent = b.parent.bone
        else:
            rootBones.add(b)
        b.force_import = False
        for c in b.children:
            if c not in bones:
                b.force_import = True
    process_armature(armobj, rootBones)
    bpy.ops.object.mode_set(mode='OBJECT')

    ctx.view_layer.objects.active = armobj.bindPose_obj
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)
    for b in bones:
        if hasattr(b, "bindPose"):
            m = b.bindPose.inverted()
            pb = create_bone (b, armobj.bindPose.edit_bones)
            pb.head = m @ Vector((0, 0, 0))
            pb.tail = m @ Vector((0, BONE_LENGTH, 0))
            pb.align_roll(m @ Vector((0, 0, 1)))
            b.poseBone = pb.name
    bpy.ops.object.mode_set(mode='OBJECT')
    for b in bones:
        if hasattr(b, "bindPose"):
            pb = armobj.bindPose_obj.pose.bones[b.poseBone]
            rb = armobj.armature_obj.pose.bones[b.poseBone]
            pb.matrix = rb.matrix

    # don't clutter the main collection if importing to a different collection
    ctx.layer_collection.collection.objects.unlink(armobj.armature_obj)
    ctx.layer_collection.collection.objects.unlink(armobj.bindPose_obj)
    ctx.view_layer.objects.active = save_active
    #however, do need to link the bindPose armature to the import collection
    mu.collection.objects.link(armobj.bindPose_obj)

    for skin in skins:
        skin.armature = armobj.armature
        skin.armature_obj = armobj.armature_obj
        skin.bindPose = armobj.bindPose
        skin.bindPose_obj = armobj.bindPose_obj

    return armobj.armature_obj

def is_armature(obj):
    # In Unity, it seems that an object with a SkinnedMeshRenderer is the
    # armature, and bones can be children of the SMR object, or even siblings
    if hasattr(obj, "skinned_mesh_renderer"):
        if obj.skinned_mesh_renderer.bones:
            return True
    return False
