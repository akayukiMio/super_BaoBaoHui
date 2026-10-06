import { FileVideo } from "lucide-react";
import { Badge, Card, CardContent, CardHeader, CardTitle, Checkbox, ScrollArea } from "./ui";
import { STATUS_TEXT, formatBytes, formatDuration, cn } from "../lib/utils";
import type { VideoFile } from "../types";

const STATUS_STYLE: Record<string, string> = {
  pending: "bg-muted text-muted-foreground",
  processing: "bg-primary/15 text-primary",
  done: "bg-accent/15 text-accent",
  skipped: "bg-muted text-muted-foreground",
  error: "bg-destructive/15 text-destructive",
  deleted: "bg-muted text-muted-foreground line-through",
};

export function VideoTable({
  files,
  onToggle,
  onToggleAll,
  disabled,
}: {
  files: VideoFile[];
  onToggle: (path: string) => void;
  onToggleAll: (checked: boolean) => void;
  disabled: boolean;
}) {
  const selectable = files.filter((f) => f.status !== "done" && f.status !== "deleted");
  const allChecked = selectable.length > 0 && selectable.every((f) => f.checked);
  const checkedCount = files.filter((f) => f.checked).length;
  const checkedSize = files.filter((f) => f.checked).reduce((s, f) => s + f.size, 0);
  const totalSize = files.reduce((s, f) => s + f.size, 0);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>视频文件列表</CardTitle>
        <span className="text-sm text-muted-foreground">
          共 {files.length} 个 · 已选 {checkedCount} 个 · 选中 {formatBytes(checkedSize)} / 总计{" "}
          {formatBytes(totalSize)}
        </span>
      </CardHeader>
      <CardContent className="p-0">
        <div className="flex items-center gap-3 border-b border-border px-5 py-2 text-sm">
          <Checkbox
            checked={allChecked}
            disabled={disabled || selectable.length === 0}
            onCheckedChange={(c) => onToggleAll(c === true)}
          />
          <span className="text-muted-foreground">全选 / 取消全选</span>
        </div>
        <ScrollArea className="h-[38vh]">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card/95 text-left text-xs text-muted-foreground">
              <tr className="[&>th]:px-5 [&>th]:py-2 [&>th]:font-medium">
                <th className="w-10"></th>
                <th>文件名</th>
                <th className="w-24 text-right">大小</th>
                <th className="w-28">分辨率</th>
                <th className="w-20">时长</th>
                <th className="w-20">状态</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.path} className="border-t border-border/60 hover:bg-accent/5">
                  <td className="px-5 py-2">
                    <Checkbox
                      checked={f.checked}
                      disabled={disabled || f.status === "done" || f.status === "deleted"}
                      onCheckedChange={() => onToggle(f.path)}
                    />
                  </td>
                  <td className="max-w-0 px-5 py-2">
                    <div className="flex items-center gap-2">
                      <FileVideo className="h-4 w-4 shrink-0 text-primary/70" />
                      <span className="truncate" title={f.path}>
                        {f.name}
                      </span>
                    </div>
                  </td>
                  <td className="px-5 py-2 text-right font-mono text-xs">
                    {formatBytes(f.size)}
                  </td>
                  <td className="px-5 py-2 text-xs text-muted-foreground">
                    {f.width ? `${f.width}×${f.height}` : "未知"}
                  </td>
                  <td className="px-5 py-2 text-xs text-muted-foreground">
                    {formatDuration(f.duration)}
                  </td>
                  <td className="px-5 py-2">
                    <Badge className={cn(STATUS_STYLE[f.status] ?? STATUS_STYLE.pending)}>
                      {STATUS_TEXT[f.status] ?? f.status}
                    </Badge>
                  </td>
                </tr>
              ))}
              {files.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-sm text-muted-foreground">
                    还没有文件。请先选择文件夹或文件进行扫描。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
