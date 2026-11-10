# A2A 附件释放接入

目标：每份附件或新回读结果首次提供内容，后续主模型调用只携带材料路径；需继续提取或复核时按需 Read。图片、原生 PDF、音频保存原始字节，Office/文本/解析后的 PDF 正文保存可读文本；视频沿用 ReadVideo。业务请求和结构化提取结果继续保留。

上线需同步三部分：

1. 使用包含附件释放中间件的 WanScope 服务并重启；中间件应在观测中间件之前执行，日志才能反映实际发送的入参。
2. 所有 A2A Agent 自动启用，无需配置、提示词声明或工具释放标记；旧 `attachment_release_marker` 仅兼容保存，不再控制行为。确认 Agent 保留 Read 与 RunSkillScript；不得限制 Read 只能在提取完成后调用。
3. 更新主提示词为本目录的 `主提示词_v0.2_编排版.md`，注册八个 `admission-v0-2-*` 技能。catalog 上传 `skills/admission-v0-2-catalog/Archive.zip`，其中含根目录 SKILL.md、清单、全部脚本和 `stdin_json.py`；其他技能上传各目录的 SKILL.md.zip。技能注册名随本版升级，需要按新名称注册，再把准入 Agent 的 `tool-config.skills` 绑定到这八个本版名称；保留其他业务技能绑定及工具配置。只更新主提示词或上传包而未更新绑定，会导致找不到本版技能。

脚本仅在无待填、无被拒行、无待复核项及 STALE 时，在 PASS 后独立输出一行 `RELEASE_ATTACHMENTS`。fill、recheck、finish 共用同一契约；compare、show 不释放。此标记仅兼容旧平台，新平台自动释放不等待它。模型不得自行输出标记代替门禁。

部署前运行：

```bash
python3 integration/package_runtime.py --write
python3 integration/package_runtime.py --check
python3 -m unittest discover -s integration -p 'test_*.py'
```

打包器从当前源码生成确定性的 zip，清单记录提示词、脚本和压缩包哈希。后续修改源码必须重新打包；`--check` 会拒绝版本漂移。

验收一次真实 A2A 任务：首次 model.call 有附件内容；第二次 model.call 中，即使没有标记，对应内联内容也消失，出现 `inputs/attachment-…` 路径；回读指定路径能取得原始媒体或解析文本；此次新回读对下一次模型调用可见，再后续变回路径；会话历史保留原内容。保存失败的附件继续内联，应查服务保存失败日志。缓存 token 较高不能代替这项验收。跨请求是否重传附件需另外查看网关请求日志。
