# 项目与保存协议

## 存储与边界

每本书是一个独立目录；不要放在技能安装目录或公开代码仓库内。所有命令显式指定 `--book`，不设置隐式全局当前书。新建目录必须尚不存在。读写使用 Python 3.9+ 标准库，无网络调用。

权威记录为项目根的 `.book-companion.json`：稳定 book_id、revision、设置、plan、outline、chapters、memory、candidates、events。章节历史/定稿存在该文件内；导出 Markdown 只是阅读副本，修改导出文件不会自动回写。先备份整个书籍目录再升级技能。此版是本地单用户工具，不提供多用户鉴权、加密或防恶意篡改。

`draft` 初稿、`reviewed` 初审、`final` 定稿与 `private` 可见性分开；脚本没有公开功能。初审仅代表作者采用了评审修订，不是外部认证。

## 调用

下列 `SKILL_DIR` 表示本技能实际目录，`BOOK_DIR` 表示作者选择的独立书籍目录；使用宿主实际路径，不把这些占位字直接传给命令。

```text
python3 SKILL_DIR/scripts/book_state.py init --book BOOK_DIR --title 未命名书稿
python3 SKILL_DIR/scripts/book_state.py status --book BOOK_DIR
python3 SKILL_DIR/scripts/book_state.py show --book BOOK_DIR --chapter ch-01
python3 SKILL_DIR/scripts/book_state.py show --book BOOK_DIR --section memory
python3 SKILL_DIR/scripts/book_state.py show --book BOOK_DIR --section events
```

`status` 仅展示最近五条工作记忆；需要时读 `show --section memory` 找较早记录。不能因为不在最近窗口就认定素材不存在。原始素材和较长分析可存项目内单独文件，记忆中保存来源、覆盖与路径，不重复把整本稿注入上下文。

创建提议前读当前 status。把下面结构写入项目内的临时候选 JSON（使用当前真实 book_id 与 revision）：

```json
{
  "book_id": "从 status 返回值复制",
  "base_revision": 0,
  "change": {"action": "settings", "data": {"title": "候选书名"}}
}
```

```text
python3 SKILL_DIR/scripts/book_state.py propose --book BOOK_DIR --input REQUEST.json
python3 SKILL_DIR/scripts/book_state.py show --book BOOK_DIR --candidate CANDIDATE_ID
python3 SKILL_DIR/scripts/book_state.py accept --book BOOK_DIR --candidate CANDIDATE_ID --confirmation 作者真实的明确指令原文
```

`propose` 只是保存待选内容，不改已采用稿。展示正文及目标后等待作者指令；不要编造确认原文。脚本只能校验结构、版本和部分歧义短答，**不能认证屏幕外的作者意图**，执行者负责保留真实来源。已有明确且具体的用户编辑指令可以作为授权，无需每个机械步骤重复询问；大幅改写、定稿或扩大范围仍单独确认。

状态写入带项目锁、临时文件和原子替换；旧 revision 或内容指纹不符时拒绝采用。锁存在先检查并发或中断，不自动删锁、不无限重试。失败不报告保存成功；恢复读 status 与目标章后再决定下一步。幂等重试已采用候选不会再建版本。

## 可提议的操作

- `settings`：局部更新 `title / author / assistant_name / mode`；mode 为 `unspecified / direct / learn`。
- `plan`：局部更新 writing-method.md 中字段，每项含 `value / status / evidence`。只把作者本轮实际确认的项设 confirmed。
- `outline`：整个有序数组，节点为 `{"id":"ch-01","title":"起点","role":"本章职责"}`。原 id 保留；支持新增、改名、重排，不支持删除既有节点。改名不改正文，旧定稿标题留在快照；导出当前稿使用新目录标题，定稿导出使用原快照标题。方案/目录签名变更后应复核既有章节与审阅，而非自动重写或重新定稿。
- `chapter`：data 必须含 `chapter_id, content_type: manuscript, text, stage, sources, change_note`。sources 是实际来源标识字符串列表，原创虚构可以为空；不是程序自动认证。stage 为 draft 或 reviewed，首次/定稿后修订必须 draft。先存在目录节点，再存正文。
- `finalize`：data 为 `{"chapter_id":"ch-01","chapter_hash":"status 中本章哈希"}`。先展示当前版本，由作者明确确认该章该版；禁止用普通“好的”或模型审阅代替。定稿保存正文、标题、方案签名和作者原话。后续改目录不改变旧定稿。

每次采用都递增 revision，旧待选项因此可能过期；不能在变更版本号后偷偷重用旧授权。成批导入目前逐项采用，不是全批原子事务；中断时明确记录哪些已经完成。

## 工作记忆和反馈

使用 `note` 保存工作记录，不把它冒充作者确认或正文。输入结构：

```json
{
  "book_id": "当前书 id",
  "base_revision": 0,
  "note": {
    "author_statements": [{"quote":"作者实际原话", "source":"当前消息或真实记录定位"}],
    "hypotheses": ["待确认的理解"],
    "questions": [{"topic":"目标读者", "status":"answered"}],
    "next_step": "下一步",
    "materials": [],
    "reviews": []
  }
}
```

```text
python3 SKILL_DIR/scripts/book_state.py note --book BOOK_DIR --input NOTE.json
```

note 也会递增 revision；最好在提议前保存本轮记忆，避免新候选立刻过期。材料记录和审阅结构见对应参考。记忆保留工作假设的历史，不是已确认事实表；回访以最新明确决定为准。

## 导出

```text
python3 SKILL_DIR/scripts/book_state.py export --book BOOK_DIR --output NEW_FILE.md
python3 SKILL_DIR/scripts/book_state.py export --book BOOK_DIR --output FINAL_FILE.md --finals
```

输出文件必须不存在，不覆盖原稿。普通导出含待写标记；`--finals` 只含每章最近定稿快照，跳过未定稿章，不能把它称为完整全书。当前标题/署名和当前章序仍取当前设置，单章定稿正文与标题取快照。
