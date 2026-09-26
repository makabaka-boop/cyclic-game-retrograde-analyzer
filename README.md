# gamegraph — 有限状态对弈的 WIN / LOSE / DRAW 分析器

双方轮流沿有向行动边移动；**没有出边的状态立即输**。有向图允许环，
因此对弈可能永远不终止——这种情况判 **DRAW（和棋）**。朴素的胜负递归会
把环整体误判成必败；本服务用逆向传播（吸引域）的最小不动点正确区分
WIN / LOSE / DRAW，并为每个结论给出可验证的见证。

## 判定规则（吸引域不动点）

对每个状态取如下规则的**最小不动点**（从所有终局 LOSE 种子出发传播）：

- **LOSE**：所有后继都是 WIN（无出边的终局状态空真成立，是 LOSE 种子）；
- **WIN**：至少有一个后继是 LOSE；
- **DRAW**：不在吸引域中的状态——双方都可以一直留在 DRAW 子图中，
  最终沿某个真实有向环无限循环。

这是标准的胜负吸引域（winning/losing attractor）算法，用队列实现，
复杂度 O(V + E)。

## 请求格式（stdin 或文件参数）

```json
{
  "states": ["s1", "s2", "s3"],
  "edges": [["s1", "s2"], ["s2", "s1"], ["s1", "s3"]],
  "queries": ["s1"]
}
```

约束：

- `states`：**2～300** 个**唯一**的非空 ASCII 字符串 id；
- `edges`：**最多 2000** 条 `[source, target]` 有向边，**边唯一**；
- 边或查询引用未知状态、状态重复、边重复 → **整份请求拒绝**
  （CLI 退出码 2，返回全部错误信息）；
- `queries` 可省略；重复查询只回答一次（按首次出现顺序）。

## 响应格式

```json
{
  "status": "ok",
  "state_count": 3,
  "edge_count": 3,
  "counts": {"WIN": 1, "LOSE": 1, "DRAW": 1},
  "states": {
    "s1": {"status": "DRAW"},
    "s2": {"status": "DRAW"},
    "s3": {"status": "LOSE", "evidence": {"terminal": true, "all_successors_win": []}}
  },
  "queries": {
    "s1": {
      "status": "DRAW",
      "draw_witness": {
        "path": ["s1"],
        "enters_cycle_at": "s1",
        "cycle": ["s1", "s2"]
      }
    }
  }
}
```

- **WIN** 状态给出 `witness.action`：一条真实出边，把对手送进 LOSE；
  当有多条时选择目标 **id 最小**的一条。
- **LOSE** 状态给出 `evidence.all_successors_win`：**全部**后继（按 id 排序）
  连同每条行动边，证明“无论怎么走都送给对方一个 WIN”；终局状态另带
  `terminal: true` 和空列表。
- **DRAW 查询**给出一条**只经过 DRAW 状态**的 `path`，最终在
  `enters_cycle_at` 进入真实有向环 `cycle`（环上状态互不相同、首尾相连）。
  裁决顺序：
  1. 先取路径长度最短者（到任意环上 DRAW 状态的最短距离，多源反向 BFS）；
  2. 长度相同再按**整条状态 id 序列字典序**裁决（等价于依次比较
     `(path, 进入的环状态, 环)` 的字典序）；
  3. 环从**最小 id** 开始表示（在等长最短环中取字典序最小者）。

拒绝时向 stderr 输出 `{"status": "error", "errors": [...]}`。

## 本地运行

纯标准库，Python ≥ 3.9：

```bash
python3 -m gamegraph --pretty examples/example.json      # 文件
cat request.json | python3 -m gamegraph                   # 标准输入
python3 -m gamegraph --pretty < request.json
```

也可作为库使用：`from gamegraph import analyze`，`analyze(payload)` 返回
普通可 JSON 序列化的字典，校验失败抛出 `gamegraph.ValidationError`。

## Docker Compose（gamegraph 服务）

```bash
# 标准输入方式
cat examples/example.json | docker compose run --rm -T gamegraph --pretty

# 挂载/拷贝进容器的文件方式
docker compose run --rm gamegraph --pretty examples/example.json
```

Compose 把当前目录以只读方式挂载到 `/workspace`，容器入口即 CLI
（`python -m gamegraph`），可追加 `--pretty` 或文件路径。

## 测试

```bash
python3 -m pytest -q
```

`tests/test_gamegraph.py` **不使用被测实现的任何算法**，独立验证：

- **吸引域不动点**：每轮从零重算的朴素单调迭代（60 个小随机图 +
  30 个中随机图 + 300 状态/2000 边极限图逐状态比对）；
- **每条见证边**：WIN 的行动边真实存在、目标确为 LOSE、且是 id 最小者；
  LOSE 证据列出全部后继且每条目标确为 WIN；
- **DRAW 见证**：
  - 小图用暴力枚举（所有最短路径 + 经过环点的全部简单环 + 最小旋转）
    精确比对 `(路径长度, 路径序列, 环起点, 环序列)` 的完整裁决；
  - 中/大图用独立多项式检查：可达环判定（BFS 自返）、多源反向 BFS 最短距离、
    分层 DP 求全局字典序最短路径、独立 BFS 验证环为经过入口的最短闭环；
- 校验类：未知状态引用、重复状态/边、非 ASCII、越界数量、畸形边等
  均整份拒绝；CLI 成功退出 0、拒绝/坏 JSON 退出 2。

## 实现说明与边界

- 主分析器：`gamegraph/analyzer.py`（校验、逆向传播队列、Tarjan SCC 找环、
  BFS 距离、分层后缀秩 DP 求字典序最短路径）。
- 环的字典序裁决：环是**旋转后**比较，而“在一般有向图中找经过指定顶点的
  字典序最小最短简单环”在最坏情况下候选最短路径数量可指数（与有向两点
  不相交路径的 NP 难问题相关）。实现逐层枚举候选最短环并设全局预算
  (`_CYCLE_WALK_CAP`)：常规对弈图为线性开销且结果精确；仅在对抗性的分层
  完全图等病态输入上触发多项式秩回退——**返回的环永远是真实、等长的最短环**，
  仅极端情况下可能不满足字典序偏好。路径裁决始终是精确多项式算法。
