# PIR / PSI Small Linux ST 扩展

本公开仓库只交付自己的 PIR/PSI Small 测试、Producer 应用包和适配工具。原 System-test 是私有依赖：接收方使用自己有权限取得的 Runtime，本仓库不包含其源码、ZIP 或其他测试用例。

当前状态：**软件验证及交叉构建已具备验收流程；实体 HPU、RTL 执行和实际 hart→HPU 路由尚未验证。** `SOFTWARE_FLOW_PASS` 不能作为硬件 PASS。

## 版本及固定用例

- Producer：`adamsir32/inline-asm@5a0f7898da265a6c92e6f73331a540c8fc8d38a9`。
- 应用包保留原始构建提交 `2622761537c7dcd73a89da3482da1d65c2b9c9b5`，不改写其历史来源。在原构建服务器直接比较确认，两版本代码、依赖及 CMake 输入相同，差异为交付文档。目录 tree ID 和文件 SHA-256 在 `packages/inputs.lock.json`。
- PIR CPU 分解／编码复用 `adamsir32/nexus-am@61baacec`；与服务器原提交 `c738b84e` 的完整 Git tree 相同。Nexus-AM 不是本工程的测试目标。
- 外部 Runtime 的接口版本由 `config/runtime-contract.json` 中的文本摘要约束；摘要统一 LF，不公开私有源码。不同版本须先审查兼容性，不能直接跳过检查。

| 参数 | PSI Small | PIR Small |
| --- | --- | --- |
| BFV N / 明文模数 | 8192 / 65537 | 4096 / 2056193 |
| 密钥模数链 | 2146713601, 2146959361, 2147074049, 2147205121, 2147352577 | 2147205121, 2147295233, 2147352577, 2147377153 |
| 用例 | Sender 1–10；Receiver 1、101–104；交集 {1} | 128×1024 字节；4×4 布局；目标记录 8 |
| HPU 指令数 | 2891 | Stage0 17740；Stage1 26700 |
| 导入镜像字节（含 guard） | 5910784 | Stage0 7875840；Stage1 11676928 |
| 输出 limb 数 | 8 | Stage0 16；Stage1 32 |

这些是公开的固定测试数据，安全级别为 0，不是生产安全参数。PIR CPU 得到 32 个明文多项式，再编码并覆盖 96 个 Stage1 动态 limb；其余 6 个固定 plaintext limb、密钥和 twiddle 均保持不变。没有重新实现 PIR/PSI 算法或新增 HPU 算子。

## 构建

开发环境：Linux、Python 3（tarfile 支持 `filter`）、宿主 C/C++17 编译器、CMake >=3.22、Git、RISC-V Linux 交叉编译器、SSH/SCP。

```sh
make SYSTEM_TEST=/path/to/authorized/System-test \
  CROSS_COMPILE=riscv64-linux-gnu-
make offline
make test SYSTEM_TEST=/path/to/authorized/System-test
```

第一条命令生成两个独立 ELF 和 `group_08`，检查所有 15 个项目目标文件无 V 指令，并比较 ELF 固定入口和包内 HPU 指令流。外部 Runtime 的 `st_common.o`、`st_dual.o` 也在检查范围内；不把静态系统库的指令归为项目源码检查。

`build/board-receipt.json` 记录源码、Runtime、编译选项、ELF 和部署输入摘要。部署前会拒绝已变化的源码或构件。可执行文件必须和同次构建的镜像、Golden、权限位图一起部署。

`make offline` 首次从公开 Producer 仓库取得固定版本，仅构建宿主 modified-SEAL；禁用 GSL、ZLIB、ZSTD、HEXL 等可选依赖，不需要为板卡编译 SEAL。后续可离线复用。也可复用已有本机构建：

```sh
make offline SEAL_SOURCE=/path/to/modified-SEAL SEAL_BUILD=/path/to/host-seal-build
```

源码摘要仍须与固定 Producer 对应；已有构建若启用了可选依赖，可传入 `SEAL_CPPFLAGS`、`SEAL_LIBS`。不要将 RISC-V SEAL 库传给宿主链接器。

## 密钥与离线语义验证

`packages/keys/` 中是**有意公开的固定测试私钥**，只对应本仓库固定 fixture。它们在原 Producer 环境导出，交付前通过所有包输出的实际解密和最终语义比较验证。接收方不再调用 KeyGenerator，不依赖标准库随机分布重现密钥。

导入／部署前检查密钥文件 SHA-256；验证器加载 SEAL SecretKey 后再次检查参数和密钥数据的 BLAKE2b-256 指纹。私钥只留在开发机，不上传板卡。`tools/export_test_keys.cpp` 仅用于维护者迁移 fixture，不能在接收方运行时重建或替换密钥。

独立检查示例（仅表示语义检查，不是 HPU 运行证明）：

```sh
./build/verify_psi output/RUN/results/psi-lane0.u32.bin packages/keys/psi.secretkey.seal
./build/verify_pir output/RUN/results/pir-stage1-lane0.u32.bin packages/keys/pir.secretkey.seal
```

PSI 恢复四个密文并检查每个元素的 8 个 felt，与 CPU 集合交集比较。PIR 恢复 Stage1 密文，解密、重组、再次解密并逐字节核对目标记录。两者拒绝不规范系数、错误密钥、零噪声预算和不完整镜像。

## 双 lane 的硬件前置条件

目前没有板卡或接线证据，不能推断实际 hart→HPU 路由已正确。`config/routing.example.json` 明确标记 `unconfirmed`，直接部署会拒绝。

接收方需要根据**实际板卡/bitstream 的 RTL、板卡说明或测量记录**提供路由文件，填写 Linux CPU ID、设备树 hart ID、对应 HPU、CSR/DDR 地址、板卡标识及证据文件 SHA-256。仅将示例中的 status 改成 confirmed 不构成路由核实；证据必须说明该对应关系。不要假设 Linux CPU 编号等于 hart 编号。

运行时每个 lane 绑定到指定单个 CPU，并核对 `/sys/devices/system/cpu/cpuN/of_node/reg` 的大端 hart ID。缺少节点、绑定失败、hart 不符均失败。此检查确认调度位置，CPU→HPU 接线仍以所提供的硬件证据为依据。

其他板卡条件沿用原 Runtime：root、允许对应 `/dev/mem` 区域、自定义 HPU 指令、用户态缓存维护指令、独立保留的 DDR 区域、支持多代发令屏障。每个 lane 使用独立基址，DDR 间隔 64 MiB。

## 一次完整验收

```sh
TARGET_HOST=BOARD_IP TARGET_USER=root ROUTING_FILE=/path/to/confirmed-routing.json \
  BINARY=group_08 sh scripts/deploy_run.sh
```

脚本完成：本地构件校验 → 建立唯一 run 目录 → 上传并校验 ELF/镜像/Golden/位图 → 双 lane 执行 → 无论用例成功或失败均尝试下载现场 → 核对运行身份及完整性 → 两 lane 的 PSI/PIR 解密 → 汇总 `acceptance.json`。私钥不包含在上传包中。

`output/<UTC时间-随机ID>/` 保存构建身份、路由证据、传输日志、板卡返回码、逐阶段 DDR/JSON 和语义日志。不会复用旧输出；板卡文件使用 O_EXCL 创建。只有本次构件一致、板卡返回 0、两个 lane 所有阶段完整、Golden/只读区/guard 和语义检查均通过，才给出 `HPU_ACCEPTANCE_PASS`。

单用例也可设置 `BINARY=st08_01_psi_small` 或 `st08_02_pir_small`。离线复核整次已收集运行：

```sh
python3 scripts/verify_run.py output/RUN
```

## 内存保护及失败现场

HPU 可写位图来自实际 DSTORE 子区间，包含合法 scratch 和输出；其余输入、密钥、twiddle、空洞和 64 行尾部 guard 必须不变。输出另外逐字比较 Golden，并在初始镜像中用非规范值毒化，防止未执行误通过。

PIR CPU 编码前后只允许 96 个声明输入发生变化，固定区域（包括 scratch/output 的初始值）不得被 CPU 误写。发令前保存 CPU 实际输入快照；Stage1 完成后这些输入对 HPU 也是只读的。

PSI、PIR Stage0、PIR Stage1 在 Golden 失败时也会保存现场。可返回的超时/fault 会保存 `completed=false` 的诊断镜像，不能作为成功证据。SIGKILL、进程崩溃或设备永久卡死可能来不及导出；收集器会将缺失现场判为失败，已有现场仍保留。诊断镜像不是设备冻结快照。

## 软件证据与尚未完成项

`make test` 使用测试专用 Mock HPU 写入已知输出，运行真实 ST 控制流、CPU 算法及原双 lane Runtime；它不执行硬件算术。该路径只允许输出 `SOFTWARE_FLOW_PASS`、`hardware_verified=false`。包括只读区/guard/输出/CPU 输入损坏、scratch 合法写、超时、旧运行、缺失 lane、错误密钥和传输失败等检查。

最新软件构建与验证记录见 `logs/software-checks.txt`。实体 HPU 执行、实际路由、缓存一致性、IRQ/PSYNC 重入和故障后的设备恢复仍待接收方在板卡验收；没有将历史软件 PASS 升格为真实 HPU PASS。
