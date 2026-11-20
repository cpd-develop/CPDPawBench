# 判别性证据脚本（反向变异与只读探针）

`test_` 与 `review_` 里"删掉修复就会红""改位置就会红"这类结论，全部由这里的脚本产出。
它们不是测试套件的一部分，**不要挂进 CI**：CI 里跑一条会就地改源码的脚本，等于给
下一个接手的人准备一次不明原因的脏工作区。

## 怎么跑

```
cd /Users/anderson/Desktop/ClawParterner/CPDPawBench
/Users/anderson/Desktop/ClawParterner/.venvs/pawbench-eval/bin/python \
    pal_sdd/feat_acp_remote_eval/reverse_checks/reverse_round8.py
```

脚本顶部的 `REPO` 是绝对路径（写死在每台开发机上），换机器只需改这一行；正因为如此，
归档的这份与跑出记录数字的那份**逐字节一致**——没有顺手改成 `__file__` 推导，否则
"这条数字是哪次运行产出的"又要靠回忆。

## 三条使用约束

1. **不与任何读者并行。** 变异脚本 `reverse_*.py` 会临时改写 `pawbench/cpd/**` 再在
   `finally` 里恢复；恢复之后逐个文件比对 sha256（`reverse_plugin.py` 改写的是
   `plugins/pawbench-eval/**`，`test_plugin.py` 读的是文件而不是模块，所以它只能这么做）。
   运行期间若有独立检视者或另一个会话
   正在读同一批文件，它读到的是被打掉守卫的版本，结论会失去意义。探针 `probe_*.py`
   只读，可以随时跑。
2. **锚点与它盯的代码是同一份要维护的资产。** 每条变异靠一段固定文本定位要替换的位置，
   代码改了而锚点没跟上时，脚本打印 `SKIP` 并把这一条**计入幸存者**——`SKIP` 不是通过，
   是"这一条没被证成"。改完 `datasets.py`／`store.py`／`reports.py` 顺手核对锚点。
   **第三类：内存变异插件**（`unlock_plugin.py`）用 `-p` 挂进 pytest，在导入后替换模块
   属性，源码一个字节不动——检视者正在读文件时，这是唯一能做的反向验证。代价是它只能
   替换"模块级可替换的东西"，锚点失效不会报 `SKIP` 而是静默无效，所以跑完要确认红的
   正是预期那条断言。
3. **BASELINE 预检。** 每个脚本先跑一遍相关用例，不绿就直接中止，避免把"用例本来就红"
   误报成"变异判红"。

## 每个脚本对应哪一批

| 脚本 | 检的是 | 变异／探针条数 | 最近一次实测 | 记录位置 |
|---|---|---|---|---|
| `reverse_l17.py` | 第八批：L17 并发闸 | 3 | 3/3 判红、零幸存者（第六轮改写顶掉其锚点、报 `SKIP`，修正后重跑） | `test_` §4.15、`review_` 第六轮 |
| `reverse_round6.py` | 第九批：第六轮 8 项发现 | 8 | 8/8 判红、零幸存者（第七轮修正锚点 `NAMES_BEFORE_COPY` 后重跑；第十三批重跑 BASELINE 9 passed → 8/8 判红，锚点未失效） | `test_` §4.16、`review_` 第六轮 |
| `reverse_round7.py` | 第十批：L18 四类重复全量工作 | 7 | 7/7 判红、零幸存者（第十一批修正 `CACHE_ON`／`SIGNATURE_CHECK`／`CACHE_BOUND`／`SUBSET_READ` 四条锚点后重跑；第十二批把 `tasks_for_run` 的函数体加长，`SUBSET_READ` 再次报 `SKIP`，改成整段函数体锚点后重跑；第十三批重跑 BASELINE 5 passed → 7/7 判红，锚点未失效） | `test_` §4.17、`review_` 第七轮 |
| `reverse_round8.py` | 第十一批：第七轮 1 严重 + 2 项修复 | 5 | BASELINE 3 passed → 5/5 判红、零幸存者（第十三批重跑同样 5/5，锚点未失效） | `test_` §4.18、`review_` 第七轮 |
| `reverse_round9.py` | 第十二批：第八轮 2 严重 + 3 项修复 | 11 | BASELINE 7 passed → 首跑 9/11 判红、**2 条幸存者**（成因见下节），补齐后 11/11 判红、零幸存者（第十三批重跑同样 11/11，锚点未失效） | `test_` §4.20、`review_` 第八轮 |
| `reverse_round10.py` | 第十三批：L35 四个 config 默认锚点 | 4 | BASELINE 27 passed → 4/4 判红、零幸存者，`finally` 恢复后 sha256 一致 | `test_` §4.21、`review_` L35 |
| `probe_round7.py` | 分类计数/索引缓存/报告遍数的**计数探针** | 3 段 | `{'office tooling': 1}`；md 报告 `{bodies:2, job_tasks:3}`（L33 的实测依据） | `review_` 第七轮发现 3／4 |
| `probe_race7.py` | 索引缓存淘汰的并发探针 | 1 段 | 300 轮 × 6 线程 = 1800 次 `describe`，`errors=none`（加锁前同脚本报 6 次 `KeyError`） | `review_` 第七轮发现 1 |
| `probe_resolve_m3.py` | M3 提交表单 resolve 面板的**耗时探针**（只读，sqlite 建在 scratch 目录，仓库零写入） | 5 段 | 真语料 + `pilot_v1`：`resolve` **0.03ms**、`describe` 0.7–1.3ms、`list_catalog` 0.8–1.3ms、`list_categories` <0.01ms、`tasks_for_run`(15 题正文) **9–18ms**（两次运行 ~15ms 与 ~9ms，同机有别的负载，判据用量级不用某个毫秒数） | `design_` §12 原型评审问题 2 |
| `probe_grader_race.py` | 第十四批：并发判分对 `sys.modules["subprocess"]` 的污染 + 脚本子进程输出是否进服务 stdout（只读，**每个测量各起一个子进程**） | 5 个 stagger + 2 种 import 位置 | 两次运行 `intact` 分别 **2/5** 与 **0/5**（结果取决于调度）；坏掉那次 5/5 留下 wrapper，随后一次无关 `subprocess.run` 也被打印。泄漏：脚本顶层 import `False`、`grade()` 体内 import `True`（`exec` 在换模块之前），打出 cmd/returncode/stdout/stderr 四行。**第一版用 `redirect_stdout` 在线程里捕获，它自己也是进程级的，吞掉了另一条线程的输出——那次运行不算证据** | `test_` §4.22、`review_` L39 |
| `probe_grader_nest.py` | 第十四批：留下的 wrapper 会不会嵌套放大（只读） | 3 轮重叠 + 1 次无关调用 | 3 轮后一次 `echo` 打出 **3 份** wrapper 块，marker 出现 **6** 次（3 cmd + 3 stdout）；层数只增不减 | `test_` §4.22、`review_` L39 |
| `unlock_plugin.py` | 第十四批：`test_grading.py` 的三条用例是否真能判红（**内存变异**，源码零写入，检视期间可跑） | 1 | `PYTHONPATH=/tmp … -m pytest tests/cpd/acp_remote_eval/test_grading.py -q -p unlock_plugin` → **1 failed, 2 passed**，红在 `assert 2 == 1`（peak）；不挂插件 → **3 passed** | `test_` §4.22 |
| `reverse_round11.py` | 第十五批：judge 通道 12 条新用例是否真能判红（**内存变异**，7 条，源码零写入，检视期间可跑） | 7 | BASELINE **15 passed** → 首跑 **5/7**、2 条幸存者（`BACKOFF_CAP` 锚点错：`_delay` 是方法不是模块全局；`FENCE_LOST` 用例自指：断言等于自己按值 import 的常量）→ 两处修掉后 **7/7 判红、零幸存者** | `test_` §4.23 |
| `reverse_plugin.py` | M4 插件（skill 侧）：`test_plugin.py` 的 7 条宿主契约用例（**文件级改写** + 逐字节还原，改的是 `plugins/**` 不是 `pawbench/**`） | 7 | BASELINE **7 passed** → **7/7 判红、零幸存者**，`finally` 还原后 `diff -r` 与运行前备份一致。首版还原用 `mkdir(exist_ok=True)`，本机 shim 对已存在目录抛 `EEXIST`、还原中断删掉插件里 6 个文件（已按原文重建）；现改为"只为缺失目录 mkdir" + 逐文件 sha256 复核。变异 `DEPS_MOVED` 改同目录改名（`backend/` 那半只留正向断言，删新目录在本机报 `EISDIR`） | `test_` §4.28 |

表里"最近一次实测"是这批 diff 出门前的数字，不是永久事实——脚本可重跑，结论要以重跑
为准。

## 第九轮首跑的两条幸存者

幸存者是这套脚本唯一的产出。两条都指向真问题，但**指向的东西不一样**：一条是用例把顺序
交给了调度器，一条是变异体本身与修复等价。

1. `the write-and-measure step given no lock (reports.py)` — 判绿。
   用例 `test_two_requests_for_one_fingerprint_agree_on_the_file_that_landed` 原本让两个
   线程在 `_render` 里各睡 0.05 s，指望它们同时到达写入点；实际上去掉锁之后，输的一方
   那次 `path.is_file()` 复查通常已经能看到赢家落盘的文件，于是直接返回赢家的指纹，与
   加锁版本无法区分。**补齐的办法不是加断言，是把顺序钉死**：改成让第一个进入 `_write`
   的调用睡 0.2 s，另一个必然在它落盘前通过复查、写入自己的字节，两份答案的 `sha256`
   必然不同 → 判红。谁被拖慢不影响结论，所以也不依赖哪个线程先跑。
   锁本身是真的，理由写进了 `_ensure_report_file` 的 docstring：`generated_at` 在 payload
   里、不在指纹里，同一指纹的两次渲染字节不同。
2. `the category write de-duplicated but still removing one copy (datasets.py)` — 判绿。
   这一条是**等价变异体**：用例摆的旧行是同一个字符串两次（`["field kit", "field kit"]`），
   `dict.fromkeys` 已经把它压成一份，"删第一份"与"删全部"在这份数据上是同一段代码，换
   任何用例都判不红。它指的缺口在源码里：`assign_categories` 去重用的是**原样字符串**，
   比较用的却是**归一化名字**，所以一行里存着 `"Field Kit"`／`"field  kit"` 时 `remove`
   永远够不着它，`delete_category` 也就永远拒绝。改成读取时归一化，用例改摆两种拼法，
   变异体换成 `RAW_DEDUPE_ONLY`（保留"删全部"、只去掉归一化）→ 判红。

一句话记法：**判绿先问"这条变异在这份数据上是否与修复等价"**。等价就说明用例摆的数据
不够刁，或者修复有一半是装饰——两种都要动源码或用例，不是动脚本。
