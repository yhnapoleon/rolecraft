# 公共接口检查

在登记工作区的锁定Python环境执行，给每次检查一个新的证据目录：

```sh
.venv/bin/python docs/integration/check_public.py --artifacts runs/local/checks/public-run-01
```

脚本选取80cf1f6真实已有测试，再加公共v2契约与原前端后端兼容测试；不设-k排除，保存精确命令、选集、显式环境、runner hash、退出码和日志hash。它使用独立临时目录，不与其他pytest进程共享。环境只继承代码列出的非秘密变量，并固定PYTHONPATH到当前源码；不继承提供器密钥或PG变量。此命令默认SQLite，PG用独立测试命令与库验证。

原test_freeze现按BASE ls-tree枚举真实既有场景；新增v2 baseline不冒充旧原件，走其包manifest与语义检查。旧失败证据未改，未扩大跳过范围。

旧323/398检查的现存runner已保全并hash，按固定源码重建的324/399选中节点分别随旧运行证据保存。那些脚本在原执行时的hash及完整继承环境没有保存，补充记录明确这个边界，不补造过去记录。
