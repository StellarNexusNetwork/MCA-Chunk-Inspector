# ⚠️ 注意！使用风险提示

- 本脚本由 **AI 生成**，可能存在未知 bug  
- 可能 **造成未知后果**  
- 请自行备份重要数据后使用  
- 使用时请自行承担风险  
- （readme也是ai写的 我完全不知道它是不是在胡言乱语 总之我用这个工具得到了我想要的了）

---

# MCA Chunk Inspector

一个用于读取特大 Minecraft 区块文件 (`.mca`) 的 Python 工具。  
它可以从 region 文件中提取并解析单个区块（chunk），并在数据损坏时尽量恢复。

<img width="2402" height="133" alt="3b230f18d3b9ab78c8895d6b37b9e2b5" src="https://github.com/user-attachments/assets/a19b0c2c-d94a-4708-bb4f-dc23826bdf93" />

<img width="863" height="485" alt="fdc15694-0f37-477b-a147-779c894f5057" src="https://github.com/user-attachments/assets/49ba279b-72e8-4001-9972-25b8fdf3fea3" />

（遭受bug重创的gtnh2.8存档的末地 👎）（这行不是ai写的）


---

## 功能

- 读取超大 `.mca` region 文件  
- 提取指定坐标的区块数据   
- 输出区块内容为 JSON  
- 可额外保存原始压缩体或解压后的 NBT 数据  

---

## 环境要求

- Python 3.8 或更高  
- 至少安装以下库之一：  
  - `nbtlib`（推荐）  
  - `python-nbt`

安装示例：

```bash
pip install nbtlib
# 或者
pip install python-nbt
```

---

## 使用方法

```bash
python mca_chunk_inspector.py --mca <文件路径> --cx <chunk_x> --cz <chunk_z> [可选参数]
```

示例：

```bash
python mca_chunk_inspector.py \
  --mca ./World/DIM1/region/r.0.0.mca \
  --cx 0 --cz 0 \
  --out chunk_0_0.json \
  --raw-nbt-out chunk_0_0.nbt
```

---

## 参数说明

| 参数 | 必填 | 类型 | 说明 |
|------|:----:|------|------|
| `--mca` | 是 | `str` | `.mca` region 文件路径，如 `World/DIM1/region/r.0.0.mca` |
| `--cx` | 否 | `int` | 区块 X 坐标，可为绝对或 region 内坐标，默认 0 |
| `--cz` | 否 | `int` | 区块 Z 坐标，默认 0 |
| `--out` | 否 | `str` | 输出 JSON 文件名（含诊断信息和解析结果），默认 `chunk_out.json` |
| `--raw-nbt-out` | 否 | `str` | 解压后的 NBT 二进制输出文件，可在 NBTExplorer 或 Amulet 中打开 |

---

## 输出内容

脚本会生成一个 JSON 文件，结构类似：

```json
{
  "diagnostics": {
    "mca": "World/DIM1/region/r.0.0.mca",
    "chunk": {"cx": 0, "cz": 0},
    "found": true,
    "offset_sector": 2,
    "sector_count": 3,
    "length": 4136960,
    "compression_byte": 2,
    "errors": []
  },
  "nbt": {
    "Level": {
      "xPos": 0,
      "zPos": 0,
      "Entities": [...],
      "TileEntities": [...]
    }
  }
}
```

如果区块无法解析，会额外生成：
- `chunk_out.decompressed.nbt`：解压但未解析的 NBT 二进制  
- `chunk_out.chunk_compressed.bin`：原始压缩体（当解压失败时）

---

## 常见用法

### 查看区块基本信息

```bash
python mca_chunk_inspector.py --mca ./World/DIM1/region/r.0.0.mca --cx 0 --cz 0
```

只输出诊断信息。

---

### 导出可视化用的 NBT 文件

```bash
python mca_chunk_inspector.py \
  --mca ./World/DIM1/region/r.0.0.mca \
  --cx 0 --cz 0 \
  --out chunk_0_0.json \
  --raw-nbt-out chunk_0_0.nbt
```

生成：
- `chunk_0_0.json`：解析结果  
- `chunk_0_0.nbt`：可导入 NBTExplorer、Amulet 等工具查看

---

使用示例：

```bash
python mca_chunk_inspector.py --mca ./World/DIM-1/region/r.-1.2.mca --cx 0 --cz 0
```

---

## 常见问题

### 1. “No NBT parsing library available”
未安装 NBT 库。  
执行：
```bash
pip install nbtlib
```

### 2. “Decompression error”
压缩数据损坏。程序会自动尝试扫描恢复，并保存：
- `.chunk_compressed.bin`
- `.decompressed.nbt`

---

## 许可

MIT License
