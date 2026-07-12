# 参与贡献

感谢参与 CableLaySim。Issue、讨论、测试工况、文档修订和代码贡献都很有价值。

## 开始之前

1. 先搜索已有 Issue，避免重复工作。
2. 缺陷报告请附操作系统、Python/Node 版本、输入参数、复现命令和实际结果。
3. 算法改动请先说明物理问题、适用范围和验证方法。
4. 不要提交商业软件安装文件、许可证、专有模型或无再分发权的数据。

## 本地检查

```powershell
python -m unittest discover -s backend/tests -v

cd frontend
npm ci
npm test -- --run
npm run build
```

## Pull Request 要求

- 保持改动聚焦，并说明用户可见影响。
- 新增或修改的输入应标明单位、坐标方向和数据来源。
- 新增或修改的输出应标明物理定义、采样时刻和文件字段。
- 算法改动应包含测试，并提供与解析解、实测数据或成熟软件的同口径对比。
- 不允许通过隐藏修正系数或经验拟合层让结果贴合参考软件。
- 前后端接口变更应同步修改 Python schema、TypeScript 类型和 README。

## 提交建议

提交信息使用简洁的动词开头，例如：

```text
fix contact transition tension definition
add synchronized ADCP input adapter
document realtime sensor timing contract
```

## 数据与结果

大型结果文件不要直接提交到仓库。优先提供生成脚本、小型公开样例和结果摘要；需要共享大文件时，请在 Issue 或 Pull Request 中说明公开下载位置和许可证。
