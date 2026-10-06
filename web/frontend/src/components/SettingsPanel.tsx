import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle, Label, Select, Slider, Switch } from "./ui";
import type { EncodersResp, CompressionSettings } from "../types";

const AUDIO_OPTIONS = ["64k", "96k", "128k", "192k", "256k", "320k"].map((v) => ({
  value: v,
  label: v,
}));

export function SettingsPanel({
  encResp,
  settings,
  onChange,
  disabled,
  onBrowseOutput,
}: {
  encResp: EncodersResp | null;
  settings: CompressionSettings;
  onChange: (patch: Partial<CompressionSettings>) => void;
  disabled: boolean;
  onBrowseOutput: () => void;
}) {
  const encKey = settings.encoder;
  const meta = encResp?.encoders[encKey];
  const isCpu = meta?.quality_param === "crf";
  const qLabel = isCpu ? "质量 (CRF)" : "质量 (CQ)";
  const qHint = isCpu
    ? "值越小质量越高、文件越大（推荐 26-30）"
    : encKey === "av1_nvenc"
    ? "值越小质量越高、文件越大（推荐 24-28）"
    : "值越小质量越高、文件越大（推荐 22-26）";
  const presetHint = isCpu ? "越慢压缩率越好，但耗时越长" : "p1 最快、p7 质量最好（推荐 p5）";

  const encoderOptions = (encResp?.available ?? []).map((k) => ({
    value: k,
    label: encResp!.encoders[k].label,
  }));
  const presetOptions = (meta?.presets ?? []).map((p) => ({ value: p, label: p }));
  const scaleOptions = (encResp?.scale_options ?? []).map((s) => ({ value: s, label: s }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>压缩设置</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="编码器">
            <Select
              value={settings.encoder}
              disabled={disabled}
              options={encoderOptions}
              onValueChange={(v) => {
                const m = encResp?.encoders[v];
                onChange({ encoder: v, crf: m?.default_q ?? settings.crf, preset: m?.default_preset ?? settings.preset });
              }}
            />
          </Field>
          <Field label="编码速度预设">
            <Select
              value={settings.preset}
              disabled={disabled}
              options={presetOptions}
              onValueChange={(v) => onChange({ preset: v })}
            />
            <Hint>{presetHint}</Hint>
          </Field>
        </div>

        <Field label={`${qLabel}：${settings.crf}`}>
          <div className="flex items-center gap-4">
            <Slider
              min={18}
              max={40}
              step={1}
              value={[settings.crf]}
              disabled={disabled}
              onValueChange={([v]) => onChange({ crf: v })}
              className="flex-1"
            />
            <span className="w-8 text-right font-mono text-sm">{settings.crf}</span>
          </div>
          <Hint>{qHint}</Hint>
        </Field>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field label="最大分辨率">
            <Select
              value={settings.max_resolution}
              disabled={disabled}
              options={scaleOptions}
              onValueChange={(v) => onChange({ max_resolution: v })}
            />
          </Field>
          <Field label="输出子文件夹">
            <input
              className="h-9 w-full rounded-lg border border-input bg-background/60 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              value={settings.output_subdir}
              disabled={disabled || !!settings.custom_output_dir}
              onChange={(e) => onChange({ output_subdir: e.target.value })}
            />
          </Field>
          <Field label="音频码率">
            <Select
              value={settings.audio_bitrate}
              disabled={disabled}
              options={AUDIO_OPTIONS}
              onValueChange={(v) => onChange({ audio_bitrate: v })}
            />
          </Field>
        </div>

        <div className="space-y-3 rounded-xl border border-border bg-muted/30 p-4">
          <div className="flex items-center justify-between">
            <Label>自定义输出目录</Label>
            <Switch
              checked={!!settings.custom_output_dir}
              disabled={disabled}
              onCheckedChange={(c) =>
                onChange({ custom_output_dir: c ? settings.custom_output_dir || " " : "" })
              }
            />
          </div>
          {settings.custom_output_dir !== "" && (
            <div className="flex items-center gap-2">
              <input
                className="h-9 flex-1 rounded-lg border border-input bg-background/60 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder="输出到指定目录（镜像源文件夹结构）"
                value={settings.custom_output_dir.trim()}
                disabled={disabled}
                onChange={(e) => onChange({ custom_output_dir: e.target.value })}
              />
              <button
                type="button"
                className="h-9 rounded-lg border border-input bg-background/60 px-3 text-sm hover:bg-accent/10 disabled:opacity-50"
                disabled={disabled}
                onClick={onBrowseOutput}
              >
                浏览…
              </button>
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-6">
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={settings.force_compress}
              disabled={disabled}
              onCheckedChange={(c) => onChange({ force_compress: c })}
            />
            强制压缩高效编码源文件 (HEVC/AV1/VP9)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={settings.overwrite}
              disabled={disabled}
              onCheckedChange={(c) => onChange({ overwrite: c })}
            />
            覆盖已存在的输出文件
          </label>
        </div>
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function Hint({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted-foreground">{children}</p>;
}
