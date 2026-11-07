# Home Assistant 小米空调伴侣集成

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat&logo=home-assistant&logoColor=white)](https://github.com/marsdream/homeassistant-xiaomi-acpartner)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.4%2B-41BDF5.svg?style=flat&logo=home-assistant&logoColor=white)](https://www.home-assistant.io)
[![License](https://img.shields.io/badge/License-Apache%202.0-D22128.svg?style=flat&logo=apache&logoColor=white)](LICENSE)
[![Support on Ko-fi](https://img.shields.io/badge/Support%20on-Ko--fi-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/aitoken)
[![GitHub Release](https://img.shields.io/github/v/release/marsdream/homeassistant-xiaomi-acpartner?label=release)](https://github.com/marsdream/homeassistant-xiaomi-acpartner/releases)

把**小米（绿米）空调伴侣**接入 Home Assistant：本地 MiIO 协议直连，**不需要米家 App、不需要云端账号**，
支持**红外遥控学习**、**内置铃声**、**FM 收音机**，以及**语音播报（TTS）**。

<p align="center">
  <a href="https://github.com/marsdream/homeassistant-xiaomi-acpartner"><img src="docs/images/hacs-install.png" alt="一键安装 via HACS" width="320" /></a>
</p>

<p align="center">
  <sub>点上面按钮 → 在 HACS 里添加自定义仓库 <code>https://github.com/marsdream/homeassistant-xiaomi-acpartner</code> → 搜「空调伴侣」→ 下载 → 重启 HA</sub>
</p>

## 支持的设备

| 型号 | 说明 | 状态 |
|---|---|---|
| 绿米 / 小米 空调伴侣 V2（`lumi.acpartner.v2`） | 带红外、FM、语音 | ✅ 已实测 |
| 小米 空调伴侣 V1（`lumi.acpartner.v1`） | 无语音 | ⚠️ 协议相近，未实测 |

> **绿米空调伴侣 P3**（`lumi.acpartner.acn05`）是**另一套协议**，本集成**不支持**。
> P3 没有本地音频上传接口，MiIO 方法集也完全不同。

## 能力一览

| 功能 | 说明 |
|---|---|
| `media_player` | 播放内置铃声、FM 电台、上传的音频 |
| `remote` | 红外遥控：学习红外码、发送红外码 |
| `speak` 服务 | 把一段文字渲染成语音在设备上播放，播完自动删除 |
| `upload_audio` | 让设备自己通过 HTTP 下载音频并存下来 |
| `cleanup_audio` | 手动清理设备上残留的音频文件 |
| FM 电台列表 | 设备内置的电台频道表 |
| 设备信息 | 型号、固件版本、负载功率、Wi-Fi 信号 |

## 安装

### HACS（推荐）

把这个仓库加进 HACS 的自定义仓库：

```
https://github.com/marsdream/homeassistant-xiaomi-acpartner
```

然后 HACS → 集成 → 搜「空调伴侣」→ 下载 → 重启 Home Assistant。

### 手动

把 `custom_components/xiaomi_acpartner` 整个目录拷到你的 HA 配置目录（通常是 `/config` 或 `~/.homeassistant`）：

```
<config>/custom_components/xiaomi_acpartner/
```

重启 Home Assistant。

### 依赖

`manifest.json` 里已经声明 `python-miio` 和 `edge-tts`，HA 启动时会自动装。

> `edge-tts` 走的是微软 Edge 的在线语音接口，**不需要注册也不需要 API key**，
> 但需要设备能访问外网。如果你的网络访问不到，可以在本集成的**选项**里配置一个自建的
> TTS 服务作为备用（见下）。

## 配置

**设置 → 设备与服务 → 添加集成 → 搜「空调伴侣」**

| 字段 | 说明 |
|---|---|
| `host` | 设备在局域网里的 IP，例如 `192.0.2.100` |
| `token` | MiIO token，32 位十六进制字符串 |
| `name` | 显示名称 |
| `area` | 房间（添加完也能在设备页改） |

### 怎么找设备的 IP 和 token

IP：看路由器（小米 / 华为 / tp-link 都行）的设备列表，找名字带 `lumi.acpartner` / `空调伴侣` 的那台。

token：需要在米家 App 里抓一次，或者用 `python-miio` 探测：

```bash
python3 -m miiocli discover
```

拿到 token 后填进去即可。提交时集成会自动探测设备、读取型号与固件、注册设备。

> ⚠️ token 相当于设备密码，**不要**贴到 GitHub issue 里。

### 选项（集成 → 配置 → 三个齿轮）

| 字段 | 说明 |
|---|---|
| `tts_base_url` | 设备能访问到的 Home Assistant 地址，例如 `http://192.0.2.50:8123`。语音播报必需。 |
| `tts_api_url` | 可选。Edge 语音不可用时的**备用** TTS 服务地址，留空即不使用。 |
| `tts_api_key` | 可选。备用 TTS 服务的 API key。 |

只要 Edge 语音能用，后两项**留空即可**，开箱即用。

## 用法

### 语音播报

```yaml
action: xiaomi_acpartner.speak
target:
  entity_id: media_player.living_room_air_conditioning_companion
data:
  message: "今天最高温度6度，最低温度1度，出门记得加衣服。"
  speaker: zh-CN-XiaoxiaoNeural
```

参数：

| 字段 | 默认 | 说明 |
|---|---|---|
| `message` | 必填 | 播报文本，最多 300 字 |
| `volume` | 设备当前音量 | 0-100 |
| `speaker` | `zh-CN-XiaoxiaoNeural` | 微软 Edge 音色名 |
| `api_key` | 选项里的值 | 备用服务的 key，仅在 Edge 不可用时需要 |

> ⚠️ 设备只有约 **11 MB** 空闲空间，而且**原样保存**上传的文件（不转码）。
> 所以本集成在上传前会检查体积和剩余空间，播完自动删除设备上的文件。
> 单条播报建议不超过 300 字。

常用音色：`zh-CN-XiaoxiaoNeural`（女声）、`zh-CN-YunxiNeural`（男声）、
`zh-CN-XiaoyiNeural`、`zh-CN-YunjianNeural`。

### 红外学习与发送

走 Home Assistant 标准 `remote` 平台，服务就是内置的那几个：

```yaml
# 开始学习红外码
action: remote.learn_command
target:
  entity_id: remote.living_room_air_conditioning_companion
data:
  command: "power"
  device: "空调"
  timeout: 30

# 发送已学到的红外码
action: remote.send_command
target:
  entity_id: remote.living_room_air_conditioning_companion
data:
  command: "power"
  device: "空调"
```

界面上则是 **设置 → 设备与服务 → 遥控器 → 添加遥控器 → 学习红外码**。

默认红外槽位是 30。

### 播放铃声 / FM / 上传音频

```yaml
# 内置铃声
action: xiaomi_acpartner.play_ringtone
data:
  entity_id: media_player.living_room_air_conditioning_companion
  ringtone_id: 10002
  volume: 60

# 上传并播放（设备自己去下载）
action: xiaomi_acpartner.upload_audio
data:
  entity_id: media_player.living_room_air_conditioning_companion
  url: "http://192.0.2.50:8123/local/audio/chime.mp3"

# 清理设备上的音频
action: xiaomi_acpartner.cleanup_audio
data:
  entity_id: media_player.living_room_air_conditioning_companion
```

FM 电台直接用 `media_player` 实体播放，`source` 填 `FM 频道号`（如 `1`）。

## 已知限制

- **只支持单台设备**：一个 config entry 对应一个 IP。多个设备就添加多次。
- **不支持自动发现**：HA 跑在容器里（Docker / OrbStack）时，容器的网段和家里设备的网段往往不一样，
  广播包过不去，所以只能手填 IP。
- **语音依赖外网**：`edge-tts` 需要访问微软的语音接口。不通的话请自建 TTS 并在选项里填地址。
- **红外是单向的**：设备只能发红外码，收不到空调的反馈状态。
- **设备很慢**：单核设备每次 MiIO 查询都会打断正在播放的音频。本集成在播放期间**完全停止轮询**，
  但复杂指令仍然可能有延迟。

## 技术细节

协议是小米 MiIO（UDP `54321`），token 用 AES-128-CBC 加密。

语音播报的链路：

```
文本 → edge-tts → MP3 → ffmpeg 转 ADTS AAC → 写入 HA 的 www 目录
     → 设备通过 HTTP 下载 → 播放 → 播完自动删除
```

> 设备只认 AAC/AMR/WAV，直接给 MP3 播不出来，所以要转一次。
> `ffmpeg` 用 HA 容器自带的版本，不用额外装。

## 致谢

- [python-miio](https://github.com/rytilahti/python-miio) —— MiIO 协议实现
- [edge-tts](https://github.com/rany2/edge-tts) —— 微软 Edge 语音接口

## License

[Apache License 2.0](LICENSE)

## 支持我

这个集成是纯开源、免费的，没有广告也没有付费墙。如果你觉得它让一台闲置的空调伴侣重新有了用，
欢迎请我喝杯咖啡 —— 所有赞助都会用在买新硬件和折腾新项目上。

<p align="center">
  <a href="https://ko-fi.com/aitoken"><img src="https://img.shields.io/badge/Support%20on-Ko--fi-FF5E5B?logo=ko-fi&logoColor=white&style=for-the-badge" alt="Support on Ko-fi" height="42" /></a>
</p>

---

## 更多

<p align="center">
  <a href="https://osp.io"><img src="docs/images/osp.io-logo.png" alt="开源派 osp.io" width="96" /></a>
</p>

<p align="center">
  本项目来自 <a href="https://osp.io">开源派 osp.io</a> —— 一个分享新奇、有趣、实用的
  <b>免费开源软硬件</b> 的中文社区。折腾旧硬件、拆解协议、把厂商 App 扒掉换成
  本地直连，正是开源派最爱干的事。
</p>

<p align="center">
  想看更多这种「把厂商的壳扒掉」的项目？去 <a href="https://osp.io">osp.io</a> 逛逛。
</p>
