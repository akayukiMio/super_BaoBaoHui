import { useEffect, useRef } from "react";
import { FolderOpen } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui";

export function LogConsole({ logs }: { logs: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [logs]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>日志</CardTitle>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <FolderOpen className="h-3.5 w-3.5" /> 日志文件位于项目 logs/ 目录
        </span>
      </CardHeader>
      <CardContent className="p-0">
        <div
          ref={ref}
          className="h-[26vh] overflow-auto rounded-b-2xl bg-muted/40 p-4 font-mono text-xs leading-relaxed text-foreground/90"
        >
          {logs.length === 0 ? (
            <span className="text-muted-foreground">（暂无日志）</span>
          ) : (
            logs.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap break-all">
                {line || "\u00A0"}
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}
