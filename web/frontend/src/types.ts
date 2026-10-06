export interface VideoFile {
  path: string;
  name: string;
  size: number;
  duration: number;
  width: number;
  height: number;
  codec: string;
  status: string;
  output_path: string | null;
  output_size: number;
  error_msg: string;
  encode_seconds: number;
  progress: number;
  checked: boolean;
}

export interface EncoderMeta {
  label: string;
  codec: string;
  quality_param: string;
  default_q: number;
  default_preset: string;
  presets: string[];
}

export interface EncodersResp {
  available: string[];
  encoders: Record<string, EncoderMeta>;
  scale_options: string[];
  supported_extensions: string[];
}

export interface CompressionSettings {
  encoder: string;
  crf: number;
  preset: string;
  output_subdir: string;
  max_resolution: string;
  audio_bitrate: string;
  custom_output_dir: string;
  force_compress: boolean;
  overwrite: boolean;
}

export interface DirEntry {
  name: string;
  path: string;
  size?: number;
}

export interface BrowseResp {
  path: string;
  parent: string | null;
  dirs: DirEntry[];
  files: DirEntry[];
  error: string;
}

export interface DeletableItem {
  path: string;
  name: string;
  size: number;
  output_path: string;
}

export interface ProgressState {
  is_processing: boolean;
  is_paused: boolean;
  overall: { current: number; total: number };
  file_progress: number;
  current_file: string;
  speed_text: string;
}
