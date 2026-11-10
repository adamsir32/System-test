# PIR / PSI Small Linux ST 扩展

本仓库提供供 System-test 使用的 PIR/PSI Small 应用扩展。接收方需自行准备有权限使用的原 System-test 工程；本仓库不包含该工程的源码。扩展链接原工程的 `st_common.c`、`st_dual.c`，沿用双 lane、MMIO、缓存、完成轮询和结果报告接口。

两个用例已完成交叉构建和软件路径检查，**尚未在真实 HPU 上运行**。构建成功和软件检查不代表硬件通过。

## 1. 目录结构

- `src/`：应用用例、包数据接入、SEAL 客户端检查，以及指定 Nexus-AM 基线的 PIR CPU 分解和编码。
- `scripts/`：应用包导入、用例清单生成、SEAL 依赖准备和部署运行。
- `tools/`：来自 Nexus-AM 基线的包解析与布局生成代码。
- `packages/`：Producer Small 应用包、PIR CPU 输入映射和 PSI 测试集合及布局。
- `scripts/cases.tsv`：用例清单；`python3 scripts/gen_cases.py` 更新组运行器、`CASE_STATUS.md` 和 `blocked.tsv`。

## 2. 版本与应用包

参考基线为 `adamsir32/nexus-am@61baacec` 和 `adamsir32/inline-asm@5a0f7898`。包原始构建记录为 `2622761537c7dcd73a89da3482da1d65c2b9c9b5`；服务器上该提交到交付树的差异仅为交付文档。导入器保留并核验实际构建记录。

PSI 使用 single 测试集合，预处理布局由该版本 Producer 的 `--dump-preprocessing --preprocess-only` 输出。两个 SEAL 客户端使用 Producer 固定测试参数与确定性测试种子；这些种子只适用于公开测试数据。

## 3. 构建

准备 Python 3（支持 tarfile `filter`）、CMake、RISC-V Linux C/C++ 交叉工具链、curl 和完整的原 System-test：

```sh
make SYSTEM_TEST=/path/to/System-test CROSS_COMPILE=riscv64-linux-gnu-
make SYSTEM_TEST=/path/to/System-test CROSS_COMPILE=riscv64-linux-gnu- check-no-v
```

首次构建会从个人 inline-asm 仓库指定提交下载并构建其中的 modified-SEAL；如果已经取得同一版本源码，可额外设置 `SEAL_SOURCE=/path/to/inline-asm/third_party/modified-SEAL`。无需构建 Producer。`make` 调用原工程的清单检查，验证扩展生成文件，导入包并检查应用参数、指令字、DMA 布局、镜像和 Golden，然后交叉编译两个独立用例和 `group_08`。

## 4. 部署和运行

在扩展仓库根目录执行：

```sh
TARGET_HOST=192.168.1.100 TARGET_USER=root BINARY=group_08 ./scripts/deploy_run.sh
```

`BINARY` 也可指定 `st08_01_psi_small` 或 `st08_02_pir_small`。脚本复制可执行文件和相应镜像、Golden，随后在目标板运行。板卡需支持原 System-test 的 `/dev/mem` 访问、用户态 HPU 自定义指令和缓存操作，以及其双 lane CSR/DDR 地址。每条用例由两个 lane 各运行一份，均通过才算通过。

## 5. 检查和结果

PSI 用例从 DDR 读取结果，逐字比较 SEAL Golden，使用 SEAL 解密并与 CPU 计算的集合交集比较。PIR 先检查 Stage0 Golden，使用实际 Stage0 DDR 输出执行 CPU 分解和编码；96 个动态输入与参考布局比较后，复用固定 Stage1 指令并检查 Golden，最终通过 SEAL 解密恢复并比较目标记录。实际 DDR 映像分别导出为 `psi-output-lane*.u32.bin` 和 `pir-output-lane*.u32.bin`。

日志遵循原工程的 `[HPU][PASS|FAIL|NOT_QUALIFIED]` 及组汇总格式；结果以真实目标板退出码和日志为准。此交付尚无真实硬件执行结果。
