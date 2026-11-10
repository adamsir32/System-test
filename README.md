# PIR / PSI Small System-test 扩展

本扩展只测试我们自己的 Producer 应用：PSI Small，以及 PIR Small 的 Stage0 → CPU 分解/编码 → Stage1。
基于原始 `System-test-main.zip` 的 Linux ST 组织方式，使用原 Runtime 的双 Lane、MMIO、缓存维护和 PASS/FAIL/SKIP。
原 System-test 为私有依赖，接收方自行取得授权源码；本仓库不发布其源码、ZIP 或其他 ST/IT 用例。

**本次完成交叉构建和软件实验，尚未执行真实 HPU。软件 Mock 的结果不能作为板卡 PASS。**

## 目录与复用关系

| 文件/目录 | 职责与复用来源 |
| --- | --- |
| `Makefile` | 原 ZIP 的独立用例 + `group_XX`、RV64GC、静态链接方式；只构建 08 组两个用例 |
| `src/st08_01_psi_small.c` | 参照 `st03_01_padd_l4_n1024.c` 的 prepare/配置/屏障/执行/比较流程 |
| `src/st08_02_pir_small.c` | 参照 `st02_04_psync_rearm_mmio.c` 连续阶段与多代屏障；复用已有 PIR CPU 交接代码 |
| `src/st_group_08.c` | 原 `st_group_*.c` 的逐用例隔离、双 Lane 汇总和 PASS/FAIL/SKIP |
| `src/app_support.*` | 应用文件装载、CPU 输入边界、现场保存；内存比较直接调用原 `st_v2_*` |
| `src/pir_cpu*` | 已有 Nexus-AM PIR 分解/编码实现，不重新实现算法 |
| `src/*client.cpp`, `offline_verify.cpp`, `test_key.hpp` | 已有 PSI/PIR SEAL 客户端语义恢复，仅在开发机运行 |
| `packages/` | 既有 Producer 应用包、CPU fixture、公开固定测试私钥 |
| `scripts/import_packages.py` | 导入三阶段应用包，生成编译所需布局和文件 |
| `tools/import_package.py`, `pir_unified_layout.py` | 复用已有导入和 PIR 布局逻辑，去掉其他测试类别及交付哈希检查 |
| `tools/prepare_runtime.py` | 仅在 `build/runtime/` 生成应用参数适配后的原 Runtime |
| `scripts/deploy_run.sh` | 原 ZIP 的 SSH/SCP 方式，加必要数据文件、超时、失败现场下载 |
| `scripts/verify_results.py` | 检查本次板卡退出/阶段完成情况，并解密实际下载的输出 |
| `tests/` | 仅用于这两个 ST 的宿主故障实验；不编入板卡 ELF |

原 ZIP 的 04–07 应用用例实际是未接入 Producer 的桩，没有可直接运行的 PIR/PSI 或应用包导入器。
因此保留现有 Producer 导入和客户端算法；没有重建通用 Runtime 或额外验收框架。
不使用 SHA256SUMS、文件哈希清单、Receipt、Runtime Contract、Git 提交强制校验或路由证明 JSON。
Producer 包原有元数据随包保留，但不把来源哈希作为部署前置条件。

## 获取与接入

从 `feature/pir-psi-small-st-refactor` 工作分支取得扩展，在独立目录构建。原 Runtime 放在另一目录，使用 `SYSTEM_TEST` 指定其根目录：

```sh
export SYSTEM_TEST=/path/to/authorized/System-test-main
export CROSS_COMPILE=riscv64-unknown-linux-gnu-
make
make check-no-v
```

需要 Linux、Make、Python 3（tarfile 支持 `filter`）、RISC-V Linux GCC/objdump。
构建参数沿用 `-O2 -g -Wall -Wextra -march=rv64gc`、`-static`。
也可 `make st08_01_psi_small`、`make st08_02_pir_small` 或 `make group_08`。
原 Runtime 应包含 `src/st_common.c/.h`、`src/st_dual.c`、`src/st_insn.h`、`src/st_ntt_vectors.h` 和 `scripts/check_no_riscv_v.sh`。
其已生成的指令/NTT 头文件直接复用，应用指令使用 Producer 包内的固定发令入口，不重新编码。

原 Runtime 的 512 行窗口不足以容纳应用，构建适配仅做三件事：

1. 将 `ST_WINDOW_LINES` 扩展到三个应用镜像所需的最大值（当前 45613 行，含 guard）。原 `st_dual_child` 每 Lane 一次映射 CSR 和 DDR；PIR 两阶段复用它。
2. `st_wait_irq` 保持 IRQ/VALID/BUSY/FAULT 条件，改为单调时钟期限，默认 `ST_HPU_TIMEOUT_MS=120000`。
3. 原多代屏障不再固定 5 秒，而是复用 `ST_DUAL_TIMEOUT_MS` 的用例预算；父进程仍执行整个用例的总超时，默认 300000 ms。

原 Runtime 文件不原地修改；适配副本只在被忽略的 `build/runtime/`，不公开私有实现。
外部 Runtime 接口结构变化时需人工适配，工具会指出无法匹配的接口；没有版本/哈希门禁。
切换 Runtime、工具链或编译选项时先 `make clean` 再构建。

## 开发机离线解密与软件实验

准备宿主 GCC/G++、CMake >=3.22 和 Producer 使用的 modified-SEAL 源码。例如已有 inline-asm 仓库：

```sh
make offline SEAL_SOURCE=/path/to/inline-asm/third_party/modified-SEAL
make test
```

`SEAL_SOURCE` 默认取原 Runtime 的 inline-asm 子模块下同名目录；不存在时明确指定已有 Producer 源码。
本次实验使用 `inline-asm` 的 `feature/pir-psi-audit-fixes` 中 modified-SEAL 4.4。
不在接收方重新运行 Producer，也不要求板卡构建或安装 SEAL。
`make offline` 在 `build/seal/` 构建宿主库，禁用 GSL/ZLIB/ZSTD/HEXL，并生成 `build/verify_psi` 和 `build/verify_pir`。

`packages/keys/` 是有意公开的固定测试私钥，来自原 Producer 环境，已经对包内输出完成语义解密验证。
接收方直接加载密钥，检查 SEAL 参数与格式，并通过最终语义比较确认结果；不从种子重新生成密钥，不做文件哈希绑定。
固定种子不能保证不同标准库重建同一密钥；这些密钥只能用于此固定 fixture。
PIR 数据库字节生成使用 `0x5345414c50495232`；PSI Producer 固定 PRNG 种子首字为 `0x41505349434f4e43`，均不属于生产安全配置。

`make test` 编译测试专用 Mock，复用原 Runtime 的实际内存检查、完成状态检查、fork 和屏障代码。
Mock 只写入 Golden，不执行 HPU 算术；日志明确打印 `[SOFTWARE MOCK]`，正式结果复核会拒绝该日志。
设置 `SEAL_SOURCE` 环境变量时还会编译 PIR 客户端 ASan/UBSan 检查程序。
测试依赖先完成板卡构建和 `make offline`；`check-no-v` 使用原 Runtime 检查器检查全部 15 个项目目标文件。

## 板卡部署与验收

沿用原 System-test 的板卡条件：RISC-V Linux、root、可用的 `/dev/mem`、HPU 自定义指令、用户态缓存维护和独立保留的 DDR。
地址不变：lane0 CSR `0x08000000`、DDR `0x87000000`；lane1 CSR `0x08001000`、DDR `0x8b000000`。
每 Lane 需要至少 45613×256 字节的可用保留 DDR，两个基址间隔 64 MiB。

每 Lane 默认绑定 Linux CPU 0/1。板卡 CPU 编号不同可设置 `ST_CPU0`、`ST_CPU1` 两个环境变量。
**Linux CPU 编号不等于 hart ID；两个进程或两个 MMIO 地址也不能证明 CPU→HPU 路由。**
接收方需要根据已有板卡接线/bitstream 确认实际路由；无须填写本扩展专用的硬件 JSON 或证据清单。

开发机需已能以 SSH 密钥登录板卡。板卡需提供 `sh`、`tar`、`timeout`、`chmod` 等基础命令，开发机需 SSH/SCP、`timeout`。
从扩展仓库根目录运行：

```sh
TARGET_HOST=BOARD_IP TARGET_USER=root BINARY=group_08 sh scripts/deploy_run.sh
# 单用例
TARGET_HOST=BOARD_IP BINARY=st08_01_psi_small sh scripts/deploy_run.sh
TARGET_HOST=BOARD_IP BINARY=st08_02_pir_small sh scripts/deploy_run.sh
```

默认 `TARGET_PORT=22`、`TARGET_DIR=/root/pir-psi-st`。脚本创建新的运行目录，上传 ELF 和镜像/Golden/位图，双 Lane 执行后下载结果并离线解密。
超时、非零返回码或断连时仍尝试下载已经产生的现场；上传失败时不发令。
SSH 有连接/保活超时，传输限时 180 秒，默认板卡整次运行限时 `RUN_TIMEOUT=900` 秒，SSH 执行限时比它多 60 秒。
大幅调高单用例预算时也需相应调高 `RUN_TIMEOUT`，否则外层期限先到会失败。
私钥不上传板卡。

原工程习惯的手工运行也可使用：将 ELF 及 `build/imported/*/*.bin` 按原相对目录复制到板卡，在该目录执行：

```sh
mkdir -p output
out=$(mktemp -d output/manual-XXXXXXXX)
ST_OUTPUT_DIR="$out" ./group_08 >"$out/board.log" 2>&1
rc=$?
printf '%s\n' "$rc" >"$out/board.exit"
cat "$out/board.log"
```

把 `$out` 下载到开发机，再执行 `python3 scripts/verify_results.py /path/to/results`；单用例加 `--binary st08_01_psi_small` 或 `--binary st08_02_pir_small`。
自动脚本的本地结果在 `output/run-XXXXXXXX/`，包括 `transport.log`、`results/board.log`、`results/board.exit`、DDR 和各 Lane 语义日志。
正常完整运行应有 PSI、PIR Stage0、PIR Stage1 的两 Lane 共 6 份 DDR；PSI 和 Stage1 共 4 次离线解密检查。

板卡结果沿用 `[RESULT] hart0_rc=... hart1_rc=... hart1_done=1`、`[PASS] both_harts_checked=1` 和组 SUMMARY。
组级 `skip` 仍保留，SKIP 不代表应用通过。正式验收需要两用例、两 Lane 全部成功且无 SKIP，并通过离线语义比较。
只有真实板卡日志/退出码、完整阶段现场和最终语义都成功，脚本才输出 `[ACCEPT][PASS]`。
它不是密码学运行证明；真实板卡和实际路由由执行者确认。

PSI 固定数据为 Sender 1–10、Receiver 1/101–104，预期交集 `{1}`。
PIR 固定数据为 128 条、每条 1024 字节、4×4 布局，目标记录索引 8，必须逐字节恢复正确。

## 历史问题复核与限制

| 问题 | 7291527 状态及本次处理 |
| --- | --- |
| 重复 mmap | 仍存在：原双 Lane 已映射 512 行，应用每阶段又映射；现改为原 Runtime 一次足量映射，应用所有返回路径释放 CSR/DDR |
| HPU 执行终态 | 原来已经有 `wait_irq → completion_clear → check_status`；保留原实现并实验 BUSY/FAULT/VALID 异常，不重复修正 |
| 只读区与 Guard | 原来已有；现改用原 `st_v2_*`，允许真实 DSTORE 的 Scratch/输出，输入/密钥/twiddle/guard 不可被 HPU 改写 |
| CPU 动态输入 | 仅允许 96 个 limb，由已有 CPU 编码器生成；与 fixture 比较，更新原 shadow 后作为 HPU 只读输入；其余 6 个固定 plaintext limb 不变 |
| PIR 阶段屏障 | 原 Runtime 固定 5 秒可能误报慢 Lane；改用已有单用例总预算，保留多代同步和失败传播 |
| HPU 轮询超时 | 原来仅有 20000000 次循环；改用单调时钟毫秒期限，终态条件不变 |
| PIR 密文缓冲区 | 现有 `2*2*4096` 的清零长度已正确；保留，并用 ASan/UBSan 验证客户端；不重写算法 |
| 随机种子 | 明确区分数据库确定性生成与私钥；使用已序列化测试密钥，避免跨标准库重建 |
| 失败现场 | 原来已有 Golden 失败导出；继续保留，包括 Stage0；文件以 O_EXCL 创建，拒绝覆盖旧结果；每次部署使用新目录 |
| SSH 失败/超时 | 增加连接、保活、传输、执行期限，执行失败仍收集现场，任何失败不算验收成功 |
| 离线输出衔接 | 简化为板卡日志/退出码 + 下载 DDR + 已有客户端语义比较，删除多层 Receipt/哈希绑定 |

HPU 发令本身卡死、SIGKILL、进程崩溃或设备永久挂起时，可能来不及保存当前阶段；已保存的 Stage0 等现场仍收集，缺失结果判失败。
超时现场可能在 HPU 尚未停止时读取，仅用于诊断，不能当作稳定成功快照。
运行失败后应按原板卡规程恢复设备再重试；本扩展没有实现通用设备复位。

仍待真实 HPU 验证：实际 hart 路由、完整 PSI/PIR 指令执行、PIR 两阶段数据交接、缓存一致性、IRQ/PSYNC 重入、超时/故障恢复及重复运行。
软件实验记录见 `logs/software-checks.txt`，不得把它解释为 RTL 或真实硬件 PASS。
