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

### 1. 环境准备

准备 Linux 构建环境及有权限使用的原 System-test Runtime，安装 Python 3、GNU Make 和 RISC-V Linux 交叉编译工具链。

```sh
git clone -b feature/pir-psi-small-st-refactor https://github.com/adamsir32/System-test.git
cd System-test

export SYSTEM_TEST=/path/to/authorized/System-test-main
export CROSS_COMPILE=riscv64-linux-gnu-
```

`SYSTEM_TEST` 指向原 System-test 工程目录。Runtime 为外部依赖，本仓库不包含其私有源码。

### 2. 构建测试程序

```sh
make clean
make
```

构建完成后生成三个静态 RISC-V ELF：

- `st08_01_psi_small`：PSI Small 测试。
- `st08_02_pir_small`：PIR Small 测试。
- `group_08`：PSI 和 PIR 联合测试。

应用包导入、Runtime 适配及测试程序编译由构建过程自动完成，无需单独生成应用包。

### 3. 部署并运行

确保构建主机已配置 SSH 密钥认证，并能够通过 SSH/SCP 访问目标 HPU 板卡。

**推荐运行完整测试：**

```sh
TARGET_HOST=BOARD_IP \
TARGET_USER=root \
BINARY=group_08 \
sh scripts/deploy_run.sh
```

也可以通过 `BINARY` 单独运行：

- `st08_01_psi_small`：仅测试 PSI。
- `st08_02_pir_small`：仅测试 PIR。

板卡需运行 RISC-V Linux，并支持原 System-test 所需的 `/dev/mem`、HPU 指令执行、缓存维护及预留 DDR。默认 Lane 0/1 分别绑定 Linux CPU 0/1，可通过 `ST_CPU0`、`ST_CPU1` 调整。接收方需确认 CPU/Hart 与 HPU Lane 的实际硬件路由关系。

部署脚本自动完成测试程序及应用数据打包、SCP 上传、SSH 执行、运行日志和 DDR Snapshot 回收，以及主机端结果检查。可通过 `TARGET_PORT` 指定 SSH 端口。

### 4. 验收标准

完整运行 `group_08` 后，应同时满足：

- PSI 测试双 Lane 执行成功，Golden 比较通过。
- PIR Stage0 双 Lane 执行成功，Golden 比较通过。
- PIR Stage1 双 Lane 执行成功，Golden 比较通过。
- 六份 DDR Snapshot 均成功回收且大小符合预期。
- 板卡程序退出码为 0，主机端结果验证通过。

成功时应输出：

```text
[ACCEPT][PASS] board Golden and memory checks; actual hardware routing remains a board prerequisite
```

运行日志、部署记录、DDR Snapshot 和验证结果保存在 `output/run-*/` 中，可用于后续问题定位和验收记录。

**注意：** 本测试验证的是当前 Small 参数下的 PSI 和 PIR 工作负载。PIR 的 Stage0、Stage1 在 HPU 上执行，中间密文分解与动态输入编码由 CPU 完成。软件 Mock 测试通过不代表真实 HPU 验收通过。



## 原 Runtime 的构建适配

`tools/prepare_runtime.py` 将接收方提供的原 System-test Runtime 必要源码复制到 `build/runtime/`，只修改构建副本，不修改原工程：

- 将 DDR 映射窗口从 512 行扩大到应用镜像需要的最大值（当前 45613 行，每行 256 字节，含 guard），使两个 lane 都能装载应用数据。
- 保留原 IRQ、状态和故障判断，将 HPU 等待从固定轮询次数改为单调时钟超时；默认 120000 毫秒，可设置 `ST_HPU_TIMEOUT_MS`。
- 将双 lane 发令屏障的固定 5 秒超时改为使用单用例预算 `ST_DUAL_TIMEOUT_MS`（默认 300000 毫秒），避免 PIR 两阶段 CPU 交接较慢时误超时。

原 Runtime 继续负责 MMIO、缓存、同步和结果检查；这些适配用于容纳应用并控制等待时间。

部署时请运行 `scripts/deploy_run.sh`：它会同时传输 ELF 和 `build/imported/` 中的镜像、Golden 与布局位图；只复制 ELF 不能运行测试。PIR CPU 分解和编码仅适用于当前 Small 参数和应用包布局，不可直接用于其他规模。
