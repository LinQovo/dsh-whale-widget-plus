# models/

抠图模型放这里。**仓库不带模型权重**（IS-Net 有 170MB，超过 GitHub 单文件上限，而且模型是第三方产物），需要时用工具下载：

```powershell
py tools/download_model.py --list
py tools/download_model.py --model isnet-general-use   # 约 170MB，插画/立绘推荐
```

| 模型 | 大小 | 输入 | 说明 |
| --- | --- | --- | --- |
| `u2netp.onnx` | 4.5MB | 320×320 | 最快，精度一般（可用 `--model u2netp` 下载） |
| `u2net.onnx` | 168MB | 320×320 | U²-Net 完整版 |
| `isnet-general-use.onnx` | 170MB | 1024×1024 | **推荐**，边缘细、发丝好 |
| `birefnet-general.onnx` | ~900MB | 1024×1024 | 当前最强，但 CPU 推理慢 |

没有模型也能用：菜单里把「抠图」切成 **纯色背景**（边框连通域，扁平插画/白底很快也很准），或者 **不抠图** 直接上传原图。

模型来源：[rembg](https://github.com/danielgatis/rembg) 的发布包（MIT），模型本身 U²-Net / IS-Net / BiRefNet 各自遵循其原始许可。
