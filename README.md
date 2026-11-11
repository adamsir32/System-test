# PIR / PSI Small System-test

本仓库为 HPU 提供两个 Linux 用户态系统测试：**PSI Small** 和 **PIR Small**。测试基于翠湖 System-test 的运行环境，执行应用包中的 HPU 指令，检查实际 DDR 输出与固定 Golden。

- 本仓库：[adamsir32/System-test](https://github.com/adamsir32/System-test/tree/feature/pir-psi-small-st-refactor)
- 应用包来源：[adamsir32/inline-asm](https://github.com/adamsir32/inline-asm/tree/feature/pir-psi-audit-fixes)，基线 `5a0f7898`
- PIR CPU 分解与编码代码来源：[adamsir32/nexus-am](https://github.com/adamsir32/nexus-am/tree/feature/pir-psi-audit-fixes)，基线 `61baacec`

仓库已包含 PSI、PIR Stage0 和 Stage1 的 Small 应用包，使用时无需重新生成。

原 System-test 为外部依赖，需要自行取得授权；本仓库不包含其私有源码。

## 测试做什么

- **PSI**：执行 HPU 程序并比较固定 Golden。
- **PIR**：执行 Stage0，读取 DDR 输出，由 CPU 分解密文并编码 Stage1 动态输入；复用固定 Stage1 指令执行，比较固定 Golden。

每个测试由两个 lane 各执行一次。

## 测试参数

| 参数 | PSI Small | PIR Small |
| --- | --- | --- |
| BFV 多项式次数 N | 8192 | 4096 |
| 明文模数 | 65537 | 2056193 |
| 密钥系数模数链 | 2146713601、2146959361、2147074049、2147205121、2147352577 | 2147205121、2147295233、2147352577、2147377153 |
| 数据模数链 | 上列前 4 个，逐级去掉末项 | 上列前 3 个，逐级去掉末项 |
| 数据集 | 发送方 1–10；接收方 1、101、102、103、104 | 128 条记录，每条 1024 字节，4×4 布局 |
| 查询结果 | 预期交集 `{1}` | 查询记录索引 `8` |
| 固定测试种子 | `[0x41505349434f4e43, 1, 2, 3, 4, 5, 6, 7]` | `[0x5345414c50495232, 1, 2, 3, 4, 5, 6, 7]`；数据库种子 `0x5345414c50495232` |

以上参数用于固定测试数据，Golden 比较检查密文输出。

| 应用包 | HPU 指令数 | DDR 镜像大小（含 guard） | Golden 大小 |
| --- | ---: | ---: | ---: |
| PSI | 2,891 | 5,910,784 字节 | 262,144 字节 |
| PIR Stage0 | 17,740 | 7,875,840 字节 | 262,144 字节 |
| PIR Stage1 | 26,700 | 11,676,928 字节 | 524,288 字节 |

PIR Stage0 输出经 CPU 处理后生成 **96 个动态输入 limb**，每个 4096 个 32 位字；它们的 DDR 位置根据应用包布局生成。Golden 用于逐项检查 HPU 输出。

## 构建和运行

1. 获取本仓库和有权限使用的原 System-test，准备 Linux、Python 3、Make、RISC-V Linux 交叉编译器：

   ```sh
   git clone -b feature/pir-psi-small-st-refactor https://github.com/adamsir32/System-test.git
   cd System-test
   export SYSTEM_TEST=/path/to/authorized/System-test-main
   export CROSS_COMPILE=riscv64-linux-gnu-
   ```

2. 构建板卡测试：

   ```sh
   make
   ```

   生成 `st08_01_psi_small`、`st08_02_pir_small` 和 `group_08`。

3. 配置好 SSH 密钥，并根据板卡实际 CPU/hart 到 HPU 的连接确认路由，然后部署运行：

   ```sh
   TARGET_HOST=BOARD_IP TARGET_USER=root BINARY=group_08 sh scripts/deploy_run.sh
   ```

   `BINARY` 也可设为 `st08_01_psi_small` 或 `st08_02_pir_small`；端口可用 `TARGET_PORT` 指定。脚本上传程序和数据，运行后下载 DDR 输出，并检查板卡退出状态、阶段结果及下载文件。结果与日志保存在 `output/run-*/`。

板卡需运行 RISC-V Linux，并支持原 System-test 所需的 `/dev/mem`、HPU 指令、缓存维护及预留 DDR。默认 lane 0/1 分别绑定 Linux CPU 0/1，可通过 `ST_CPU0`、`ST_CPU1` 调整；CPU 编号与实际 hart 路由需要由板卡配置确认。



## 原 Runtime 的构建适配

`tools/prepare_runtime.py` 将接收方提供的原 System-test Runtime 必要源码复制到 `build/runtime/`，只修改构建副本，不修改原工程：

- 将 DDR 映射窗口从 512 行扩大到应用镜像需要的最大值（当前 45613 行，每行 256 字节，含 guard），使两个 lane 都能装载应用数据。
- 保留原 IRQ、状态和故障判断，将 HPU 等待从固定轮询次数改为单调时钟超时；默认 120000 毫秒，可设置 `ST_HPU_TIMEOUT_MS`。
- 将双 lane 发令屏障的固定 5 秒超时改为使用单用例预算 `ST_DUAL_TIMEOUT_MS`（默认 300000 毫秒），避免 PIR 两阶段 CPU 交接较慢时误超时。

原 Runtime 继续负责 MMIO、缓存、同步和结果检查；这些适配用于容纳应用并控制等待时间。

部署时请运行 `scripts/deploy_run.sh`：它会同时传输 ELF 和 `build/imported/` 中的镜像、Golden 与布局位图；只复制 ELF 不能运行测试。PIR CPU 分解和编码仅适用于当前 Small 参数和应用包布局，不可直接用于其他规模。
