"""Video editing tools for Blender using the mouse"""
from math import floor

import bpy
from bpy.props import BoolProperty, IntProperty, EnumProperty, FloatProperty
from .functions.sequences import find_strips_mouse, find_effect_strips, get_frame_range
from operator import attrgetter
# import blf


def find_snap_candidate(frame=0):
    """
    Finds and returns the best frame snap candidate around the frame
    """
    closest_cut_frame = 1000000
    for s in bpy.context.sequences:
        start_to_frame = frame - s.frame_final_start
        end_to_frame =  frame - s.frame_final_end
        distance_to_start = abs( start_to_frame )
        distance_to_end = abs(end_to_frame)
        smallest_distance = min(distance_to_start, distance_to_end)

        if smallest_distance == distance_to_start:
            snap_candidate = frame - start_to_frame
        else:
            snap_candidate = frame - end_to_frame

        if abs(frame - snap_candidate) < abs(frame - closest_cut_frame):
            closest_cut_frame = snap_candidate
    return closest_cut_frame



# FIXME: 122, "sorted_sequences = sorted(bpy.context.selected_sequences, key=attrgetter('frame_final_start'))[0]"
# If trimming the start of the first sequence, there's no sequence selected. https://github.com/GDquest/GDquest-VSE/issues/1
class MouseCut(bpy.types.Operator):
    """Cuts, trims and remove gaps with mouse clicks"""
    bl_idname = "power_sequencer.mouse_cut"
    bl_label = "PS.Mouse cut strips"
    bl_options = {'REGISTER', 'UNDO'}

    select_mode = EnumProperty(
        items=[('mouse', 'Mouse', 'Only select the strip hovered by the mouse'
                ), ('cursor', 'Time cursor',
                    'Select all of the strips the time cursor overlaps'),
               ('smart', 'Smart',
                'Uses the selection if possible, else uses the other modes')],
        name="Selection mode",
        description=
        "Cut only the strip under the mouse or all strips under the time cursor",
        default='smart')
    cut_mode = EnumProperty(items=[('cut', 'Cut', 'Cut the strips'), (
        'trim', 'Trim', 'Trim the selection')],
                            name='Cut mode',
                            description='Cut or trim the selection',
                            default='cut')
    auto_move_cursor = BoolProperty(
        name="Auto move cursor",
        description=
        "When trimming the sequence, auto move the cursor if playback is active",
        default=True)
    cursor_offset = IntProperty(
        name="Cursor trim offset",
        description=
        "On trim, during playback, offset the cursor to better see if the cut works",
        default=12,
        min=0)
    select_linked = BoolProperty(
        name="Use linked time",
        description=
        "In mouse or smart mode, always cut linked strips if this is checked",
        default=False)

    remove_gaps = BoolProperty(
        name="Remove gaps",
        description="When trimming the sequences, remove gaps automatically",
        default=False)
    cut_gaps = BoolProperty(
        name="Cut gaps",
        description="If you click on a gap, remove it",
        default=True)
    snap = BoolProperty(
        name="Snap trim",
        description="When trimming, snap to closest cuts",
        default=False)

    @classmethod
    def poll(cls, context):
        return context is not None

    def invoke(self, context, event):
        sequencer = bpy.ops.sequencer
        anim = bpy.ops.anim
        selection = bpy.context.selected_sequences

        x, y = context.region.view2d.region_to_view(
            x=event.mouse_region_x,
            y=event.mouse_region_y)
        frame, channel = round(x), floor(y)

        if self.snap and self.cut_mode == 'trim':
            old_frame = frame
            frame = find_snap_candidate(frame)
            print("old {!s} / new {!s}".format(old_frame, frame))

        anim.change_frame(frame=frame)
        select_mode = self.select_mode

        # Strip selection
        sequencer.select_all(action='DESELECT')
        to_select = find_strips_mouse(frame, channel, self.select_linked)

        if select_mode in ('mouse', 'smart'):
            if to_select:
                for s in to_select:
                    s.select = True
            elif select_mode == 'mouse':
                return {"CANCELLED"}
        if select_mode == 'cursor' or (not to_select and select_mode == 'smart'):
            for s in bpy.context.sequences:
                if s.frame_final_start <= frame <= s.frame_final_end:
                    s.select = True

        if self.cut_mode == 'cut':
            if self.cut_gaps and len(bpy.context.selected_sequences) == 0:
                bpy.ops.sequencer.gap_remove(all=False)
            else:
                sequencer.cut(frame=bpy.context.scene.frame_current,
                              type='SOFT',
                              side='BOTH')
        elif self.cut_mode == 'trim':
            start, end = get_frame_range(bpy.context.selected_sequences)


            # Find strips to delete
            to_delete = []
            delete_start, delete_end = 0, 0
            if abs(frame - start) <= abs(start - end) / 2:
                delete_start = start
                delete_end = frame
            else:
                delete_start = frame
                delete_end = end
            for s in bpy.context.sequences:
                if delete_start <= s.frame_final_start <= delete_end and delete_start <= s.frame_final_end <= delete_end:
                    to_delete.append(s)

            # Trim and delete strips
            bpy.ops.power_sequencer.smart_snap(side='auto')
            sequencer.select_all(action='DESELECT')
            for s in to_delete:
                s.select = True
            sequencer.delete()

            if self.remove_gaps:
                anim.change_frame(frame=frame - 1)
                sequencer.gap_remove()

            # Move time cursor back
            if self.auto_move_cursor and bpy.context.screen.is_animation_playing:
                selection = bpy.context.selected_sequences
                if len(selection) > 1:
                    sorted_sequences = sorted(selection, key=attrgetter('frame_final_start'))
                    first_seq = sorted_sequences[0]
                else:
                    first_seq = selection

                frame = first_seq.frame_final_start - self.cursor_offset \
                    if abs(frame - first_seq.frame_final_start) < first_seq.frame_final_duration / 2 \
                    else frame
                anim.change_frame(frame=frame)

        sequencer.select_all(action='DESELECT')
        return {"FINISHED"}



# TODO: Double check it works
def find_strips_in_range(start_frame, end_frame, sequences = None, find_overlapping = True):
    """
    Returns strips which start and end within a certain frame range, or that overlap a certain frame range
    Args:
    - start_frame, the start of the frame range
    - end_frame, the end of the frame range
    - sequences (optional): only work with these sequences. If it doesn't receive any, the function works with all the sequences in the current context
    - find_overlapping (optional): find and return a list of strips that overlap the frame range

    Returns a tuple of two lists:
    [0], strips entirely in the frame range
    [1], strips that only overlap the frame range
    """
    strips_in_range = []
    strips_overlapping_range = []
    if not sequences:
        sequences = bpy.context.sequences
    for s in sequences:
        if start_frame <= s.frame_final_start <= end_frame:
            if start_frame <= s.frame_final_end <= end_frame:
                strips_in_range.append(s)
            elif find_overlapping:
                strips_overlapping_range.append(s)
        elif start_frame <= s.frame_final_end <= end_frame:
            if start_frame <= s.frame_final_start <= end_frame:
                strips_in_range.append(s)
            elif find_overlapping:
                strips_overlapping_range.append(s)
        if s.frame_final_start < start_frame and s.frame_final_end > end_frame:
            strips_overlapping_range.append(s)
    return strips_in_range, strips_overlapping_range



# TODO: Fix detection, currently returns wrong frames
def find_closest_surrounding_cuts(frame=0):
    """
    Returns a tuple of (left_cut_frame, right_cut_frame) of the two closest cuts surrounding a frame
    Args:
    - frame, find the closest cuts that surround this frame
    """
    start_cut_frame, end_cut_frame = 1000000, 1000000
    for s in bpy.context.sequences:
        if s.frame_final_start < frame and frame - s.frame_final_start < start_cut_frame - frame:
            start_cut_frame = s.frame_final_start
        if s.frame_final_end > frame and s.frame_final_end - frame < end_cut_frame - frame:
            end_cut_frame = s.frame_final_end
    return start_cut_frame, end_cut_frame


class MouseCreateAndFoldGap(bpy.types.Operator):
    """When you click on empty space, trims strips above and below the mouse cursor between the two closest cuts, leaves some margin and removes the gaps."""
    bl_idname = "power_sequencer.mouse_create_and_fold_gap"
    bl_label = "PS.Create and fold gap"
    bl_options = {'REGISTER', 'UNDO'}

    margin = FloatProperty(
        name="Trim margin",
        description=
        "Margin to leave on either sides of the trim in seconds",
        default=0.2,
        min=0)

    @classmethod
    def poll(cls, context):
        return context is not None

    def invoke(self, context, event):
        sequencer = bpy.ops.sequencer

        # Convert mouse position to frame, channel
        x, y = context.region.view2d.region_to_view(
            x=event.mouse_region_x,
            y=event.mouse_region_y)
        frame, channel = round(x), floor(y)

        left_cut_frame, right_cut_frame = find_closest_surrounding_cuts(frame)
        print(left_cut_frame)
        print(right_cut_frame)
        surrounding_cut_frames_duration = abs(left_cut_frame - right_cut_frame)

        margin_frame = self.margin * bpy.context.scene.render.fps

        if surrounding_cut_frames_duration <= margin_frame * 2:
            self.report({'WARNING'}, "The trim margin is larger than the gap \n Use snap trim or reduce the margin")
            return {'CANCELLED'}

        # trim_start, trim_end = left_cut_frame + margin_frame, right_cut_frame - margin_frame
        trim_start, trim_end = left_cut_frame, right_cut_frame
        strips_to_delete, strips_to_trim = find_strips_in_range(trim_start, trim_end)

        # Trim sequences that overlap with the range
        for s in strips_to_trim:
            if s.frame_final_start < trim_start and s.frame_final_end > trim_end:
                sequencer.select_all(action='DESELECT')
                s.select = True
                sequencer.cut(frame=trim_start,
                              type='SOFT',
                              side='RIGHT')
                sequencer.cut(frame=trim_end,
                              type='SOFT',
                              side='LEFT')
                strips_to_delete.append(bpy.context.selected_sequences[0])
                continue
            if s.frame_final_start < trim_end:
                s.frame_final_start = trim_end
            elif s.frame_final_end > trim_start:
                s.frame_final_end = trim_start


        # Delete all sequences that are between the cuts
        sequencer.select_all(action='DESELECT')
        for s in strips_to_delete:
            s.select = True
        sequencer.delete()
        return {'FINISHED'}


class MouseToggleMute(bpy.types.Operator):
    """Toggle mute a sequence as you click on it"""
    bl_idname = "power_sequencer.mouse_toggle_mute"
    bl_label = "PS.Toggle Mute with Mouse"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context is not None

    def invoke(self, context, event):
        sequencer = bpy.ops.sequencer

        # get current frame and channel the mouse hovers
        x, y = context.region.view2d.region_to_view(
            x=event.mouse_region_x,
            y=event.mouse_region_y)
        frame, channel = round(x), floor(y)

        # Strip selection
        sequencer.select_all(action='DESELECT')
        to_select = find_strips_mouse(frame, channel)

        if not to_select:
            return {"CANCELLED"}

        for s in to_select:
            s.mute = not s.mute
        return {"FINISHED"}


class EditCrossfade(bpy.types.Operator):
    """
    Selects handles of a crossfade strip's input and calls the grab operator
    """
    bl_idname = "power_sequencer.edit_crossfade"
    bl_label = "PS.Edit crossfade"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not context.area.type == 'SEQUENCE_EDITOR':
            self.report({'WARNING'}, "You need to be in the Video Sequence Editor to use this tool. \
                        Operation cancelled.")
            return {'CANCELLED'}

        active = bpy.context.scene.sequence_editor.active_strip

        if active.type != "GAMMA_CROSS":
            effect = find_effect_strips(active)
            if effect is None:
                self.report({'WARNING'},
                            "The active strip has to be a gamma cross for this tool to work. \
                            Operation cancelled.")
                return {"CANCELLED"}
            active = bpy.context.scene.sequence_editor.active_strip = effect[0]

        bpy.ops.sequencer.select_all(action='DESELECT')
        active.select = True
        active.input_1.select_right_handle = True
        active.input_2.select_left_handle = True
        active.input_1.select = True
        active.input_2.select = True

        bpy.ops.transform.seq_slide('INVOKE_DEFAULT')
        return {'FINISHED'}
