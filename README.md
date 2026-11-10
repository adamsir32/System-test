# PIR / PSI Small Linux ST 扩展

本仓库仅包含 PIR/PSI Small 扩展。需自行准备有权限使用的原 System-test；测试通过其 `st_common.c`、`st_dual.c` 使用双 lane、MMIO 和缓存接口。板卡测试只做 HPU DDR Golden 比较；语义解密是开发机可选步骤。当前尚未在真实 HPU 上验证。

## 测试参数

参数来自应用包 `metadata/parameters.json`、导入后的布局和 Producer；两个 BFV 配置的安全级别设置为 0，仅用于测试。

| 项目 | PSI Small | PIR Small |
| --- | --- | --- |
| BFV N / 明文模数 | 8192 / 65537 | 4096 / 2056193 |
| 密钥系数模数链 | 2146713601, 2146959361, 2147074049, 2147205121, 2147352577 | 2147205121, 2147295233, 2147352577, 2147377153 |
| 数据级模数链 | 上列前 4 个，随后逐级删末项至 1 个 | 上列前 3 个，随后逐级删末项至 1 个 |
| 数据 | 发送方 1–10；接收方 1、101、102、103、104；交集 {1} | 128 条记录，每条 1024 字节；目标记录索引 8；二维 4×4 布局 |
| 固定种子 | `[0x41505349434f4e43,1,2,3,4,5,6,7]` | `[0x5345414c50495232,1,2,3,4,5,6,7]`；数据库种子 `0x5345414c50495232` |

固定种子用于重现公开测试数据和密钥；密文仍须通过 SEAL 解密才能得到明文结果。

| 包 | HPU 指令数 | 窗口 / 导入镜像（256 字节每行） | Golden 大小 |
| --- | ---: | ---: | ---: |
| `psi.tar.gz` | 2891 | 23025 / 23089 行，5910784 字节 | 262144 字节 |
| `stage0.tar.gz` | 17740 | 30701 / 30765 行，7875840 字节 | 262144 字节 |
| `stage1.tar.gz` | 26700 | 45549 / 45613 行，11676928 字节 | 524288 字节 |

导入镜像末尾包含 64 行 guard。PSI 的 Golden 包含 8 个输出 limb；PIR Stage0 和 Stage1 分别包含 16 和 32 个输出 limb，板卡逐字与真实 DDR 比较。Stage0 输出由 CPU 分解为 32 个明文多项式，再编码为 96 个 Stage1 动态输入 limb；每个 limb 4096 个 32 位字。其物理行偏移由包清单和 `cpu-fixture.tar.gz` 的映射生成，见 `build/unified/pir_layout.c` 的 `stage0_cpu_limbs`、`stage1_cpu_limbs`；其余固定 Stage1 镜像和指令流不重新编译。每个 lane 使用原 Runtime 的独立 DDR 基址，间隔 64 MiB。

包原始构建版本为 `2622761537c7dcd73a89da3482da1d65c2b9c9b5`，与指定 `adamsir32/inline-asm@5a0f7898` 的代码和依赖目录一致，差异仅为交付文档。PIR CPU 算法取自 `adamsir32/nexus-am@61baacec`。

## 构建板卡测试

需要 Python 3（支持 tarfile 的 `filter`）、RISC-V Linux 交叉编译器及原 System-test。无需 SEAL 或网络：

```sh
make SYSTEM_TEST=/path/to/System-test CROSS_COMPILE=riscv64-linux-gnu-
make SYSTEM_TEST=/path/to/System-test CROSS_COMPILE=riscv64-linux-gnu- check-no-v
```

生成 `st08_01_psi_small`、`st08_02_pir_small`、`group_08`。清单为 `scripts/cases.tsv`，`scripts/gen_cases.py --check` 检查生成文件。

## 部署与板卡检查

```sh
TARGET_HOST=192.168.1.100 TARGET_USER=root BINARY=group_08 ./scripts/deploy_run.sh
```

`BINARY` 也可设为两个独立 ELF。需要目标板允许原 System-test 的 `/dev/mem`、HPU 指令与缓存操作。脚本上传 ELF、镜像和 Golden，运行并在成功后下载每个 lane 的完整 DDR 输出至 `output/`。组运行器或单用例返回成功只表示对应双 lane Golden 比较通过；不代表已完成离线明文语义验证。失败时脚本返回非零，输出可在目标板目录检查。

## 可选：开发机离线解密

准备相同 Producer 版本的 modified-SEAL 源码和**本机架构** SEAL 构建（不用于板卡），然后：

```sh
make offline SEAL_SOURCE=/path/to/inline-asm/third_party/modified-SEAL SEAL_BUILD=/path/to/host/seal-build
./build/verify_psi output/psi-output-lane0.u32.bin
./build/verify_psi output/psi-output-lane1.u32.bin
./build/verify_pir output/pir-output-lane0.u32.bin
./build/verify_pir output/pir-output-lane1.u32.bin
```

如 SEAL 启用了额外依赖，可通过 `SEAL_CPPFLAGS`、`SEAL_LIBS` 提供其头文件和链接参数。离线工具使用现有 SEAL 解密逻辑，将 PSI 结果与 CPU 集合交集比较，将 PIR 结果与目标记录比较；它们的 PASS 是离线语义检查结果，不是硬件运行证明。
