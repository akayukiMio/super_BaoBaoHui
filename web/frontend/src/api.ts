import type {
  BrowseResp,
  CompressionSettings,
  DeletableItem,
  EncodersResp,
  VideoFile,
} from "./types";

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

const post = <T>(url: string, body?: unknown) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => j<T>(r));

export const api = {
  health: () => fetch("/api/health").then((r) => j<{ ok: boolean; version: string }>(r)),
  ffmpeg: () => fetch("/api/ffmpeg").then((r) => j<{ available: boolean }>(r)),
  encoders: () => fetch("/api/encoders").then((r) => j<EncodersResp>(r)),
  getConfig: () => fetch("/api/config").then((r) => j<Record<string, unknown>>(r)),
  saveConfig: (config: Record<string, unknown>) =>
    post<{ ok: boolean }>("/api/config", { config }),

  browse: (path?: string) =>
    fetch(`/api/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`).then((r) =>
      j<BrowseResp>(r)
    ),
  scan: (path: string, recursive: boolean, output_subdir: string) =>
    post<{ files: VideoFile[] }>("/api/scan", { path, recursive, output_subdir }),
  select: (paths: string[]) => post<{ files: VideoFile[] }>("/api/select", { paths }),

  start: (paths: string[], settings: CompressionSettings, source_dir: string | null) =>
    post<{ ok: boolean; reason: string }>("/api/start", { paths, settings, source_dir }),
  pause: () => post<{ ok: boolean }>("/api/pause"),
  resume: () => post<{ ok: boolean }>("/api/resume"),
  stop: () => post<{ ok: boolean }>("/api/stop"),

  deletable: (subdir: string, custom_dir: string, source_dir: string | null) =>
    post<{ items: DeletableItem[] }>("/api/deletable", { subdir, custom_dir, source_dir }),
  delete: (paths: string[]) =>
    post<{ deleted: number; failed: number }>("/api/delete", { paths }),
};

export type WsEvent = { type: string; data: unknown };

export function connectWs(onEvent: (e: WsEvent) => void): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    try {
      onEvent(JSON.parse(ev.data) as WsEvent);
    } catch {
      /* ignore */
    }
  };
  return ws;
}
