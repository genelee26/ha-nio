# ha-nio

**简体中文** | [English](README.en.md)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![release](https://img.shields.io/github/v/release/genelee26/ha-nio)](https://github.com/genelee26/ha-nio/releases)
[![Buy Me A Coffee](https://img.shields.io/badge/请我喝杯咖啡-Buy_Me_A_Coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/genelee26)

把 **蔚来（NIO）** 电动车（EC6/ES6/ET5…）接入 Home Assistant 的自定义集成，基于
蔚来 iOS App 同款的私有 API（`icar.nio.com`）。蔚来没有官方 HA 集成——这个集成给你
电量、续航、门窗、驾驶状态，以及一个实时地图位置（GCJ-02 → WGS-84 已矫正，国内不偏移）。

![card](images/nio_card.png)

## 实体

| 平台 | 实体 |
| --- | --- |
| `sensor` | 电量 %、续航(CLTC)、续航(实际)、续航达成率、车辆状态、充电功率、车内/外温度、总里程、胎压 ×4（诊断）、固件版本（诊断） |
| `binary_sensor` | 驾驶、睡眠、车门、车窗、车锁、充电、云端连接（诊断） |
| `device_tracker` | 车辆位置（WGS-84，走实体注册表——重启存活） |
| `button` | 数据刷新（立即拉一次） |

轮询是自适应的，对私有 API 比较友好（刷太狠会被限流甚至导致 token 失效）：驾驶中
每 5 分钟、白天每 15 分钟、夜间每 30 分钟。所有间隔都能在集成选项里改。

## Lovelace 卡片

集成自带一张卡片 —— **NIO Car Card**，并且**自动注册**（不用手动加 Lovelace 资源、
不用额外装任何 HACS 前端插件）。集成加载后，它直接出现在「添加卡片」列表里。

卡片显示你车型的官方渲染图、一条毛玻璃状态栏（标题 + CLTC 续航）、5 个状态图标
（电量 / 驾驶 / 睡眠 / 车门 / 车窗，门窗没关会红色告警），点一下弹出完整状态弹窗 +
数据刷新按钮。

一切都在**可视化编辑器**里设置 —— 选车（NIO 设备）、车型、车身颜色全是点色卡，
不用写 YAML：

| 选项 | 作用 |
| --- | --- |
| 车辆 | 选 NIO 设备——实体按设备注册表反查，改了实体 id 也照样能用 |
| 车型 / 颜色 | 选打包的渲染图；9 个车型，每个车型全部官方配色 |
| 名称 | 卡片标题（默认 `NIO <车型>`） |
| 背景颜色 | 透明车图背后的影棚底色 |
| 背景渐变质感 | 左上亮 → 右下暗的影棚光泽（默认开） |
| 底栏颜色 / 不透明度 | 状态栏颜色与透明度；图标/文字颜色按对比度自动反色 |
| 显示文字 | 每个图标下方的状态文字；开了底栏会自动变高、车图随之缩放绝不被挡 |
| 背景图片 URL | 可选——用你自己的图盖过背景颜色 |

零前端依赖：弹窗、样式、编辑器全部自包含（不需要 `card_mod` / `browser_mod` /
`streamline-card`）。想用纯 YAML 的人，[`lovelace/`](lovelace/) 里有一份
`picture-glance` 占位符版本。

> [!NOTE]
> 车辆渲染图是厂商官方的宣传/配置器图片，为方便起见打包进来并做了裁切/羽化处理。
> 版权归蔚来公司所有，本项目不主张任何权利。

## 安装

### HACS（自定义存储库）

1. HACS → 集成 → ⋮ → *自定义存储库*
2. 添加 `https://github.com/genelee26/ha-nio`，类型选 *Integration*
3. 安装 **NIO**，重启 Home Assistant

### 手动

把 `custom_components/nio/` 拷进你 HA 的 `config/custom_components/`，然后重启。

## 配置

集成通过「重放 App 自己的请求」来认证，所以需要抓一次包：

1. 在手机和网络之间架一个 MITM 代理（mitmproxy / Reqable / Charles / Surge / Quantumult X…），
   信任它的 CA 证书。
2. 打开蔚来 App，下拉刷新车辆页。
3. 找到这条请求：
   `https://icar.nio.com/api/2/rvs/vehicle/<vehicle_id>/status?...`
4. 取两样东西：
   - **整条请求 URL**（从 `https://…/status?` 一直到末尾的 `…&sign=…`，复制全部）
   - token —— `Authorization: Bearer …` 请求**头**
5. 在 HA：*设置 → 设备与服务 → 添加集成 → NIO*，把整条 URL 粘进「抓到的状态请求 URL」框、
   token 粘进 token 框即可。

> [!IMPORTANT]
> **请勿改动那条 URL**。服务端的 `sign` 覆盖了整条查询串（字段列表+顺序、`app_ver`、
> `device_id`、`timestamp` 全在内），且这些会随 App 版本漂移（如 6.6.0 新增了 `field=key`、
> `app_ver` 也因人而异）。集成把你抓到的 URL **逐字节原样重放**，所以不要逐字段重拼——
> 那正是旧版本（≤0.2.x）一遇 App 升级就报「token 被拒」的根因（其实是签名不匹配被误报）。
> 抓到的 `sign` 不校验新鲜度，一次抓取可长期使用。URL 与 token 存在 HA 的加密配置存储里（无明文 YAML）。

> [!WARNING]
> Bearer token 是你蔚来账号的会话凭证——当密码看待。这个集成是**只读**的（从不发
> 控制指令），但 token 本身在别处足以远程控制车辆。

token 早晚会过期，到时 HA 会弹出「重新认证」通知——重新抓一个新 token 填进去即可，
不用重启。若提示是**签名被拒**（多半因 App 升级），顺手再粘一条新抓的 URL 刷新即可。

> [!NOTE]
> 从 ≤0.2.x 升级上来的现有用户**无需重新抓包**：升级时会自动把旧的逐字段数据迁移成
> 等价的整条查询串（v1→v2 迁移），原本能用的签名继续有效。

## 注意事项

- **坐标矫正**：API 返回的位置是 GCJ-02（中国大陆强制加密）。device_tracker 在内部用
  标准 7 参数法转成 WGS-84，所以 HA 地图显示真实位置。
- **门窗语义**已在真车 EC6 上实测（每个开口逐个开合、跟原始 API 抓包 1:1 对照）：
  `*_ajar_status` `1`=关、`0`=开；`vehicle_lock_status` `1`=锁、`0`=解锁；车窗
  `win_*_posn` 沿用旧 YAML 行为（`0`=关、`>0`=开）。如果你的车报值不一样，欢迎带上
  `door_status` 原始数据开 issue。
- **「电量低 → 换电提醒」刻意留作用户自建自动化**——按 `sensor.<车>_remaining_actual_range`
  在最适合你就近换电站的时间点触发。

## 赞赏支持

纯业余时间做着玩的开源项目，免费、而且会一直免费。要是它帮你省了心、或者让你会心一笑，
欢迎请我喝杯咖啡 ☕ —— 纯属鼓励，绝不影响任何功能。

[![Buy Me A Coffee](https://img.shields.io/badge/请我喝杯咖啡-Buy_Me_A_Coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/genelee26)

国内的同道也可以微信赞赏，扫下面这个码就行：

<img src="images/wechat_pay.png" width="280" alt="微信赞赏码">

谢谢每一位同道中人的鼓励 🙏

## 致谢

最初的思路 —— 抓蔚来 App 的私有 API、把数据喂进 Home Assistant —— 来自 **pangjian**
2022 年在瀚思彼岸论坛发的那篇
[《蔚来接入HA 抛砖引玉》](https://bbs.hassbian.com/thread-17594-1-1.html)。本项目就是从那套
散装 YAML 方案一路长成了完整的 HACS 集成。谢谢 pangjian 抛的砖。🙏

## 免责声明

与蔚来公司（NIO Inc.）无任何关联。使用的是未公开的私有 API，随时可能变动或失效，
风险自负。
