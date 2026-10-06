import { useCallback, useEffect, useRef, useState } from "react";
import { Moon, Sun, Save, FolderSearch, Files, Trash2, Film } from "lucide-react";
import { Toaster, toast } from "sonner";
import { api, connectWs, type WsEvent } from "./api";
import type {
  CompressionSettings,
  DeletableItem,
  EncodersResp,
  ProgressState,
  VideoFile,
} from "./types";
import { formatBytes } from "./lib/utils";
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "./components/ui";
import { SettingsPanel } from "./components/SettingsPanel";
import { FileBrowserDialog } from "./components/FileBrowserDialog";
import { VideoTable } from "./components/VideoTable";
import { ProgressPanel } from "./components/ProgressPanel";
import { LogConsole } from "./components/LogConsole";

const DEFAULT_SETTINGS: CompressionSettings = {
  encoder: "libx265",
  crf: 28,
  preset: "medium",
  output_subdir: "compressed",
  max_resolution: "原始分辨率",
  audio_bitrate: "128k",
  custom_output_dir: "",
  force_compress: false,
  overwrite: false,
};

const EMPTY_PROGRESS: ProgressState = {
  is_processing: false,
  is_paused: false,
  overall: { current: 0, total: 0 },
  file_progress: 0,
  current_file: "",
  speed_text: "",
};

function fmtEta(sec: number): string {
  if (sec < 60) return `${Math.floor(sec)}秒`;
  if (sec < 3600) {
    const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
    return `${m}分${s}秒`;
  }
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return `${h}时${m}分`;
}

export default function App() {
  const [dark, setDark] = useState(() => localStorage.getItem("vc-theme") === "dark");
  const [encResp, setEncResp] = useState<EncodersResp | null>(null);
  const [ffmpegOk, setFfmpegOk] = useState(true);
  const [settings, setSettings] = useState<CompressionSettings>(DEFAULT_SETTINGS);
  const [files, setFiles] = useState<VideoFile[]>([]);
  const [sourceDir, setSourceDir] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressState>(EMPTY_PROGRESS);
  const [logs, setLogs] = useState<string[]>([]);
  const [scanning, setScanning] = useState(false);

  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserMode, setBrowserMode] = useState<"folder" | "files">("folder");
  const [outputMode, setOutputMode] = useState(false);
  const [startConfirm, setStartConfirm] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletable, setDeletable] = useState<DeletableItem[]>([]);
  const [deletableLoading, setDeletableLoading] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const runFilesRef = useRef<string[]>([]);

  /* ---------- 主题 ---------- */
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("vc-theme", dark ? "dark" : "light");
  }, [dark]);

  /* ---------- 初始化：编码器 / FFmpeg / 配置 ---------- */
  useEffect(() => {
    api.encoders().then((r) => {
      setEncResp(r);
      setSettings((s) => {
        if (r.available.includes("hevc_nvenc") && s.encoder === "libx265") {
          const m = r.encoders["hevc_nvenc"];
          return { ...s, encoder: "hevc_nvenc", crf: m.default_q, preset: m.default_preset };
        }
        return s;
      });
    }).catch(() => toast.error("无法获取编码器列表"));

    api.ffmpeg().then((r) => {
      setFfmpegOk(r.available);
      if (!r.available) toast.warning("未检测到 FFmpeg，请安装并加入 PATH");
    });

    api.getConfig().then((c) => {
      if (c && Object.keys(c).length) {
        setSettings((s) => ({
          ...s,
          encoder: (c.encoder as string) ?? s.encoder,
          crf: (c.crf as number) ?? s.crf,
          preset: (c.preset as string) ?? s.preset,
          output_subdir: (c.output_subdir as string) ?? s.output_subdir,
          max_resolution: (c.max_resolution as string) ?? s.max_resolution,
          audio_bitrate: (c.audio_bitrate as string) ?? s.audio_bitrate,
          custom_output_dir: (c.custom_output_dir as string) ?? s.custom_output_dir,
        }));
        const last = c.last_source_dir as string | undefined;
        if (last) setSourceDir(last);
      }
    });
  }, []);

  /* ---------- WebSocket ---------- */
  const updateFile = useCallback((path: string, patch: Partial<VideoFile>) => {
    setFiles((prev) => prev.map((f) => (f.path === path ? { ...f, ...patch } : f)));
  }, []);

  const onEvent = useCallback((e: WsEvent) => {
    const { type, data } = e;
    if (type === "snapshot") {
      const d = data as ProgressState & { logs: string[] };
      setProgress({
        is_processing: d.is_processing, is_paused: d.is_paused, overall: d.overall,
        file_progress: d.file_progress, current_file: d.current_file, speed_text: d.speed_text,
      });
      if (d.logs?.length) setLogs((prev) => (prev.length ? prev : d.logs));
    } else if (type === "log") {
      const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      setLogs((prev) => [...prev.slice(-500), `[${ts}] ${data as string}`]);
    } else if (type === "log_session_paths") {
      const [r, er, dl] = data as [string, string, string];
      setLogs((prev) => [...prev, `[日志] 结果: ${r}`, `[日志] 错误: ${er}`, `[日志] 删除: ${dl}`]);
    } else if (type === "overall_progress") {
      const [cur, total] = data as [number, number];
      setProgress((p) => ({ ...p, overall: { current: cur, total } }));
    } else if (type === "file_progress") {
      setProgress((p) => ({ ...p, file_progress: data as number }));
    } else if (type === "current_file") {
      const [, , name] = data as [number, number, string];
      setProgress((p) => ({ ...p, current_file: name }));
    } else if (type === "speed_update") {
      const [mbs, eta, elapsed] = data as [number, number, number];
      const speed = mbs >= 1 ? `${mbs.toFixed(1)} MB/s` : `${(mbs * 1024).toFixed(0)} KB/s`;
      setProgress((p) => ({
        ...p,
        speed_text: `⚡ ${speed}  |  已用: ${fmtEta(elapsed)}  |  预计剩余: ${fmtEta(eta)}`,
      }));
    } else if (type === "file_status") {
      const [idx, status] = data as [number, string];
      const path = runFilesRef.current[idx];
      if (path) updateFile(path, { status });
    } else if (type === "file_status_update") {
      const d = data as VideoFile;
      updateFile(d.path, { status: d.status, progress: d.progress });
    } else if (type === "finished") {
      setProgress((p) => ({ ...p, is_processing: false, is_paused: false }));
      toast.success("压缩任务已完成");
    }
  }, [updateFile]);

  useEffect(() => {
    const ws = connectWs(onEvent);
    wsRef.current = ws;
    return () => ws.close();
  }, [onEvent]);

  /* ---------- 扫描 / 选择 ---------- */
  const doScan = useCallback(async (path: string) => {
    setScanning(true);
    setSourceDir(path);
    try {
      const { files } = await api.scan(path, true, settings.output_subdir);
      setFiles(files);
      const done = files.filter((f) => f.status === "done").length;
      toast.success(`扫描完成：${files.length} 个视频${done ? `，其中 ${done} 个已处理` : ""}`);
    } catch (e) {
      toast.error(`扫描失败：${(e as Error).message}`);
    } finally {
      setScanning(false);
    }
  }, [settings.output_subdir]);

  const onPickFolder = (path: string) => {
    setBrowserOpen(false);
    if (outputMode) {
      setSettings((s) => ({ ...s, custom_output_dir: path }));
      setOutputMode(false);
    } else {
      doScan(path);
    }
  };

  const onPickFiles = async (paths: string[]) => {
    setBrowserOpen(false);
    setScanning(true);
    try {
      const { files } = await api.select(paths);
      setFiles(files);
      toast.success(`已添加 ${files.length} 个文件`);
    } catch (e) {
      toast.error(`读取失败：${(e as Error).message}`);
    } finally {
      setScanning(false);
    }
  };

  /* ---------- 勾选 ---------- */
  const toggle = (path: string) =>
    setFiles((prev) => prev.map((f) => (f.path === path ? { ...f, checked: !f.checked } : f)));
  const toggleAll = (checked: boolean) =>
    setFiles((prev) =>
      prev.map((f) =>
        f.status === "done" || f.status === "deleted" ? f : { ...f, checked }
      )
    );

  /* ---------- 开始压缩 ---------- */
  const selectedFiles = files.filter(
    (f) => f.checked && f.status !== "done" && f.status !== "deleted"
  );
  const totalSourceSize = selectedFiles.reduce((s, f) => s + f.size, 0);

  const doStart = async () => {
    setStartConfirm(false);
    const paths = selectedFiles.map((f) => f.path);
    runFilesRef.current = paths;
    try {
      const r = await api.start(paths, settings, sourceDir);
      if (!r.ok) toast.error(r.reason || "启动失败");
      else setProgress((p) => ({ ...p, is_processing: true, overall: { current: 0, total: paths.length } }));
    } catch (e) {
      toast.error(`启动失败：${(e as Error).message}`);
    }
  };

  /* ---------- 删除已压缩源文件 ---------- */
  const openDelete = async () => {
    setDeleteOpen(true);
    setDeletableLoading(true);
    try {
      const { items } = await api.deletable(
        settings.output_subdir,
        settings.custom_output_dir.trim(),
        sourceDir
      );
      setDeletable(items);
    } catch (e) {
      toast.error(`检查失败：${(e as Error).message}`);
      setDeletable([]);
    } finally {
      setDeletableLoading(false);
    }
  };

  const doDelete = async () => {
    const paths = deletable.map((d) => d.path);
    setDeleteOpen(false);
    try {
      const r = await api.delete(paths);
      const delSet = new Set(deletable.map((d) => d.path));
      setFiles((prev) => prev.map((f) => (delSet.has(f.path) ? { ...f, status: "deleted", checked: false } : f)));
      if (r.failed > 0) toast.warning(`成功 ${r.deleted} 个，失败 ${r.failed} 个`);
      else toast.success(`已将 ${r.deleted} 个源文件移入回收站`);
    } catch (e) {
      toast.error(`删除失败：${(e as Error).message}`);
    }
  };

  /* ---------- 保存配置 ---------- */
  const saveConfig = async () => {
    await api.saveConfig({ ...settings, last_source_dir: sourceDir ?? "" });
    toast.success("设置已保存");
  };

  const patch = (p: Partial<CompressionSettings>) => setSettings((s) => ({ ...s, ...p }));
  const busy = progress.is_processing;

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4 md:p-6">
      <Toaster theme={dark ? "dark" : "light"} position="top-center" richColors />

      {/* 顶栏 */}
      <header className="glass-card flex items-center justify-between px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-soft">
            <Film className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold leading-tight">视频批量压缩工具</h1>
            <p className="text-xs text-muted-foreground">
              Web 版 · by akayukimio · {ffmpegOk ? "FFmpeg 就绪" : "FFmpeg 未检测到"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={saveConfig}>
            <Save className="h-4 w-4" /> 保存设置
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setDark((d) => !d)} title="切换主题">
            {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </Button>
        </div>
      </header>

      {/* 源文件夹 */}
      <div className="glass-card flex flex-wrap items-center gap-2 px-5 py-4">
        <span className="text-sm text-muted-foreground">源：</span>
        <span className="flex-1 truncate text-sm" title={sourceDir ?? ""}>
          {sourceDir ?? "（请选择包含视频文件的文件夹）"}
        </span>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => { setOutputMode(false); setBrowserMode("folder"); setBrowserOpen(true); }}>
          <FolderSearch className="h-4 w-4" /> 选择文件夹
        </Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => { setOutputMode(false); setBrowserMode("files"); setBrowserOpen(true); }}>
          <Files className="h-4 w-4" /> 选择文件
        </Button>
        <Button size="sm" disabled={busy || !sourceDir || scanning} onClick={() => sourceDir && doScan(sourceDir)}>
          {scanning ? "扫描中…" : "扫描"}
        </Button>
      </div>

      <SettingsPanel
        encResp={encResp}
        settings={settings}
        onChange={patch}
        disabled={busy}
        onBrowseOutput={() => { setOutputMode(true); setBrowserMode("folder"); setBrowserOpen(true); }}
      />

      <VideoTable files={files} onToggle={toggle} onToggleAll={toggleAll} disabled={busy} />

      <ProgressPanel
        progress={progress}
        hasFiles={selectedFiles.length > 0}
        onStart={() => setStartConfirm(true)}
        onPause={() => api.pause()}
        onResume={() => api.resume()}
        onStop={() => api.stop()}
      />

      <div className="flex justify-end">
        <Button variant="destructive" disabled={busy} onClick={openDelete}>
          <Trash2 className="h-4 w-4" /> 删除已压缩源文件
        </Button>
      </div>

      <LogConsole logs={logs} />

      {/* 文件浏览器 */}
      <FileBrowserDialog
        open={browserOpen}
        mode={browserMode}
        onClose={() => setBrowserOpen(false)}
        onPickFolder={onPickFolder}
        onPickFiles={onPickFiles}
      />

      {/* 开始确认 */}
      <Dialog open={startConfirm} onOpenChange={setStartConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>压缩预览确认</DialogTitle>
          </DialogHeader>
          <div className="space-y-1 text-sm">
            <p>文件数量：<b>{selectedFiles.length}</b> 个</p>
            <p>源文件总大小：<b>{formatBytes(totalSourceSize)}</b></p>
            <p>预计输出：~<b>{formatBytes(totalSourceSize * 0.5)}</b>（按约 50% 压缩率估算）</p>
            <p>输出位置：<b>{settings.custom_output_dir.trim() || `各源文件目录下的 ${settings.output_subdir} 子文件夹`}</b></p>
            <p>编码器：<b>{encResp?.encoders[settings.encoder]?.label ?? settings.encoder}</b></p>
            <p>质量：<b>{settings.crf}</b>　预设：<b>{settings.preset}</b></p>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setStartConfirm(false)}>取消</Button>
            <Button onClick={doStart}>确定开始</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除已压缩源文件</DialogTitle>
          </DialogHeader>
          {deletableLoading ? (
            <p className="text-sm text-muted-foreground">正在后台检查可删除文件…</p>
          ) : deletable.length === 0 ? (
            <p className="text-sm text-muted-foreground">没有可删除的文件。只有压缩成功且输出文件存在的源文件才可删除。</p>
          ) : (
            <div className="space-y-2">
              <p className="text-sm">
                即将删除 <b>{deletable.length}</b> 个源文件，共{" "}
                <b>{formatBytes(deletable.reduce((s, d) => s + d.size, 0))}</b>。压缩版本已存在，源文件将移入回收站（可恢复）。
              </p>
              <div className="max-h-52 overflow-auto rounded-lg border border-border p-2 text-xs">
                {deletable.map((d) => (
                  <div key={d.path} className="flex justify-between gap-2 py-1">
                    <span className="truncate" title={d.path}>{d.name}</span>
                    <span className="shrink-0 text-muted-foreground">{formatBytes(d.size)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteOpen(false)}>取消</Button>
            <Button variant="destructive" disabled={deletable.length === 0} onClick={doDelete}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

