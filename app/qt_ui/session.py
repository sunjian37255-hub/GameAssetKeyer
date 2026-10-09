"""Project operations shared by Qt controls and integration tests (no widgets)."""
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from pathlib import Path

from PIL import Image

from .. import pipeline
from ..align_utils import align_frames
from ..color_key_processor import parse_color
from ..final_result import resolve_final_result_source, resolve_pipeline_result_source, resolve_pre_alignment_source
from ..frame_sequence_exporter import export_png_frame_sequence
from ..project_manager import ProjectManager
from ..sheet_exporter import export_sheet
from ..trim_utils import trim_frames


class Session:
    def __init__(self, root):
        self.root = Path(root)
        self.manager = ProjectManager(self.root)
        self.project = None
        self.project_id = None
        self.frames = []
        self.stage_index = 0
        self.frame_index = 0

    @property
    def directory(self):
        return self.manager.project_path(self.project_id)

    @property
    def stages(self):
        return pipeline.ensure_pipeline(self.project)["stages"]

    @property
    def frame_name(self):
        return self.frames[self.frame_index].name

    def open(self, project_id):
        directory = self.manager.project_path(project_id)
        if directory.resolve().parent != self.manager.projects_root.resolve():
            raise ValueError("Invalid project directory")
        data = self.manager.load_project(project_id)
        frames = sorted((directory / "01_frames_raw").glob("frame_*.png"))
        if not frames:
            raise ValueError("No input frames found")
        self.project_id, self.project, self.frames = project_id, data, frames
        self.stage_index = self.frame_index = 0

    def save(self):
        self.manager.save_project(self.project_id, self.project)

    def params(self):
        return pipeline.effective_stage_params(self.stages[self.stage_index], self.frame_name)

    def has_override(self):
        return self.frame_name in self.stages[self.stage_index]["frame_params"]

    def apply_params(self, params, *, frame_only=False):
        parse_color(params["target_mode"], params["custom_color"])
        params = pipeline.normalize_params(params)
        if frame_only or self.has_override():
            pipeline.set_frame_params(self.project, self.stage_index, self.frame_name, params)
        else:
            pipeline.update_stage(self.project, self.stage_index, params)
        self.save()

    def clear_override(self):
        pipeline.clear_frame_params(self.project, self.stage_index, self.frame_name)
        self.save()

    def change_stage(self, action, params=None, enabled=None):
        if action == "add":
            self.stage_index = pipeline.add_stage(self.project, params)
        elif action == "duplicate":
            self.stage_index = pipeline.duplicate_stage(self.project, self.stage_index)
        elif action == "delete":
            pipeline.delete_stage(self.project, self.stage_index)
            self.stage_index = max(0, self.stage_index - 1)
        elif action in ("up", "down"):
            self.stage_index = pipeline.move_stage(self.project, self.stage_index, -1 if action == "up" else 1)
        elif action == "enable":
            pipeline.set_stage_enabled(self.project, self.stage_index, enabled)
        self.save()

    def preview_request(self):
        return deepcopy(self.project), self.directory, self.frames[self.frame_index], self.stage_index

    def trim(self, threshold, padding):
        source = resolve_pipeline_result_source(self.project, self.directory)
        if source is None:
            raise ValueError("Process all frames before trimming")
        metadata = trim_frames(source.directory, self.directory / "04_trimmed", threshold, padding, source.signature)
        self.project["trim"] = metadata
        self.save()
        return metadata

    def align(self, mode):
        source = resolve_pre_alignment_source(self.project, self.directory)
        if source is None:
            raise ValueError("Process all frames before alignment")
        metadata = align_frames(source.directory, self.directory / "05_aligned", mode=mode,
                                alpha_threshold=8, source_signature=source.signature)
        self.project["align"] = metadata
        self.save()
        return metadata

    def export(self, filename="sheet_transparent.png"):
        source = resolve_final_result_source(self.project, self.directory)
        if source is None:
            raise ValueError("Process all frames before exporting the final result")
        if self.project.get("project_type") == "video":
            metadata = export_png_frame_sequence(source, self.directory / "exports" / "final_frames")
            directory = Path(metadata["directory"])
            if len(list(directory.glob("frame_*.png"))) != len(source.frame_names):
                raise ValueError("Exported frame count does not match the final result")
        else:
            name = Path(filename)
            if name.name != filename or name.suffix.lower() != ".png" or any(c in filename for c in '<>:"/\\|?*'):
                raise ValueError("Enter a PNG filename, not a path")
            metadata = export_sheet(source.directory, self.directory / "exports",
                                    int(self.project.get("rows", 1)), int(self.project.get("cols", 1)), filename)
            directory = Path(metadata["sheet"]).parent
            if not Path(metadata["sheet"]).is_file():
                raise FileNotFoundError(metadata["sheet"])
        self.project["exports"] = metadata
        self.save()
        return directory


def render_preview(project, directory, raw_path, stage_index):
    """In-memory stage preview; final is only a resolver-approved on-disk result."""
    with Image.open(raw_path) as source:
        original = source.convert("RGBA")
    stages = pipeline.ensure_pipeline(project)["stages"]
    before = pipeline.process_pipeline_image(original, stages, stage_index - 1, raw_path.name)
    after = pipeline.process_pipeline_image(original, stages, stage_index, raw_path.name)
    final_source = resolve_final_result_source(project, directory)
    final = None
    if final_source:
        with Image.open(final_source.frame_path(raw_path.name)) as source:
            final = source.convert("RGBA")
    return {"original": original, "input": before, "result": after, "final": final}
