import { useCallback, useEffect, useState } from "react";
import { Folder, FolderUp, HardDrive, FileVideo, Check } from "lucide-react";
import { Button, Checkbox, Dialog, DialogContent, DialogHeader, DialogTitle, ScrollArea } from "./ui";
import { api } from "../api";
import { formatBytes } from "../lib/utils";
import type { BrowseResp } from "../types";

export function FileBrowserDialog({
  open,
  mode,
  onClose,
  onPickFolder,
  onPickFiles,
}: {
  open: boolean;
  mode: "folder" | "files";
  onClose: () => void;
  onPickFolder: (path: string) => void;
  onPickFiles: (paths: string[]) => void;
}) {
  const [data, setData] = useState<BrowseResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const go = useCallback(async (path?: string) => {
    setLoading(true);
    try {
      const resp = await api.browse(path);
      setData(resp);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      setSelected(new Set());
      go();
    }
  }, [open, go]);

  const toggleFile = (p: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(p) ? next.delete(p) : next.add(p);
      return next;
    });
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{mode === "folder" ? "选择文件夹" : "选择视频文件"}</DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => go()} title="我的电脑">
            <HardDrive className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!data?.parent}
            onClick={() => data?.parent && go(data.parent)}
            title="上一级"
          >
            <FolderUp className="h-4 w-4" />
          </Button>
          <input
            className="h-8 flex-1 rounded-lg border border-input bg-background/60 px-3 text-sm"
            value={data?.path ?? ""}
            readOnly
          />
          <Button
            size="sm"
            onClick={() => data?.path && onPickFolder(data.path)}
            disabled={!data?.path}
          >
            选择此文件夹
          </Button>
        </div>

        <ScrollArea className="h-[50vh] rounded-xl border border-border">
          <div className="p-2">
            {loading && <div className="p-4 text-sm text-muted-foreground">加载中…</div>}
            {data?.error && <div className="p-4 text-sm text-destructive">{data.error}</div>}

            {data && data.dirs.length > 0 && (
              <div className="mb-2">
                <div className="px-2 py-1 text-xs font-medium text-muted-foreground">文件夹</div>
                <div className="grid grid-cols-2 gap-1 md:grid-cols-3">
                  {data.dirs.map((d) => (
                    <button
                      key={d.path}
                      onClick={() => go(d.path)}
                      className="flex items-center gap-2 truncate rounded-lg px-3 py-2 text-left text-sm hover:bg-accent/10"
                    >
                      <Folder className="h-4 w-4 shrink-0 text-primary" />
                      <span className="truncate">{d.name}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {mode === "files" && data && data.files.length > 0 && (
              <div>
                <div className="px-2 py-1 text-xs font-medium text-muted-foreground">
                  视频文件（可多选）
                </div>
                {data.files.map((f) => {
                  const checked = selected.has(f.path);
                  return (
                    <button
                      key={f.path}
                      onClick={() => toggleFile(f.path)}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-accent/10"
                    >
                      <Checkbox checked={checked} onCheckedChange={() => toggleFile(f.path)} />
                      <FileVideo className="h-4 w-4 shrink-0 text-accent" />
                      <span className="flex-1 truncate">{f.name}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {formatBytes(f.size ?? 0)}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            {mode === "files" && data && data.files.length === 0 && !loading && (
              <div className="p-4 text-sm text-muted-foreground">当前目录没有视频文件</div>
            )}
          </div>
        </ScrollArea>

        {mode === "files" && (
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">已选 {selected.size} 个文件</span>
            <Button disabled={selected.size === 0} onClick={() => onPickFiles([...selected])}>
              <Check className="h-4 w-4" /> 添加所选文件
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
