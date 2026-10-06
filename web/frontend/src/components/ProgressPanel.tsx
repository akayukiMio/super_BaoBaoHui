import { Play, Pause, Square, Loader2 } from "lucide-react";
import { Button, Card, CardContent, CardHeader, CardTitle, Progress } from "./ui";
import type { ProgressState } from "../types";

export function ProgressPanel({
  progress,
  onStart,
  onPause,
  onResume,
  onStop,
  hasFiles,
}: {
  progress: ProgressState;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  hasFiles: boolean;
}) {
  const { overall, file_progress, current_file, speed_text, is_processing, is_paused } = progress;
  const overallPct = overall.total > 0 ? (overall.current / overall.total) * 100 : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>处理进度</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">总体进度</span>
            <span className="font-mono">
              {overall.current}/{overall.total}
            </span>
          </div>
          <Progress value={overallPct} />
        </div>

        <div className="space-y-1.5">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">当前文件</span>
            <span className="font-mono">{file_progress.toFixed(1)}%</span>
          </div>
          <Progress value={file_progress} indicatorClassName="bg-accent" />
        </div>

        {current_file && (
          <div className="truncate text-sm text-muted-foreground">正在处理：{current_file}</div>
        )}
        {speed_text && <div className="text-sm text-muted-foreground">{speed_text}</div>}

        <div className="flex flex-wrap gap-3 pt-2">
          {!is_processing ? (
            <Button onClick={onStart} disabled={!hasFiles}>
              <Play className="h-4 w-4" /> 开始压缩
            </Button>
          ) : (
            <>
              <Button variant="secondary" onClick={is_paused ? onResume : onPause}>
                {is_paused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
                {is_paused ? "恢复" : "暂停"}
              </Button>
              <Button variant="destructive" onClick={onStop}>
                <Square className="h-4 w-4" /> 停止
              </Button>
            </>
          )}
          {is_processing && (
            <span className="inline-flex items-center gap-2 self-center text-sm text-primary">
              <Loader2 className="h-4 w-4 animate-spin" /> 处理中…
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
