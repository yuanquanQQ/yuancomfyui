"""Server-owned RunningHub workflow catalog delivered to licensed clients."""

DEFAULT_WORKFLOW_KEY = "person_replace"


def upload(key, node_id, label, media_type="image", button_widget="upload",
           *, required=True, fallback_key=None):
    item = {
        "key": key, "node_id": str(node_id), "button_widget": button_widget,
        "label": label, "file_widget": media_type, "required": required,
    }
    if fallback_key:
        item["fallback_key"] = fallback_key
    return item


def output(node_id, media_type, *menu_actions):
    return {
        "node_id": str(node_id), "media_type": media_type,
        "menu_actions": list(menu_actions),
    }


def input_field(key, label, media_type="image", input_type=None):
    item = {"key": key, "label": label, "media_type": media_type}
    if input_type:
        item["input_type"] = input_type
    return item


def workflow(key, name, description, category, post_id, primary_input,
             inputs, uploads, outputs, *, texts=None, timeout=3000,
             minimum_run_seconds=300):
    return {
        "key": key,
        "name": name,
        "description": description,
        "category": category,
        "post_id": str(post_id),
        "timeout": timeout,
        "primary_input": primary_input,
        "inputs": inputs,
        "spec": {
            "name": key,
            "uploads": uploads,
            "texts": texts or [],
            "outputs": outputs,
            "completion": {
                "markers": ["显示报告", "Show Report"],
                "minimum_run_seconds": minimum_run_seconds,
            },
            "strict_outputs": True,
        },
    }


WORKFLOW_CATALOG = [
    workflow(
        "person_replace", "人物替换", "使用替换背景、参考人物与动作视频生成",
        "video", "2087949278193995777", "model",
        [input_field("background", "替换背景图"), input_field("video", "动作视频", "video"), input_field("model", "人物参考图")],
        [upload("background", 247, "替换背景图"), upload("model", 108, "人物参考图"), upload("video", 112, "动作视频", "video", "choose video to upload")],
        [output(119, "video", "save video", "save preview")],
    ),
    workflow(
        "ootd_7day", "OOTD 7天变装", "7 张穿搭图片生成并合成长视频",
        "video", "2087951298946752514", "day1",
        [*[input_field(f"day{day}", f"第 {day} 天图片") for day in range(1, 8)], input_field("audio", "背景音乐", "audio")],
        [*[upload(f"day{day}", node, f"第 {day} 天图片") for day, node in enumerate((6557, 6798, 6851, 7110, 7170, 7786, 7852), 1)], upload("audio", 6726, "背景音乐", "audio")],
        [output(6223, "video", "save video", "save preview")], timeout=7200,
    ),
    workflow(
        "hd_restore", "高定版高清修复", "去除 AI 感并增强图片细节",
        "image", "2087951445663510530", "image",
        [input_field("image", "待修复图片")], [upload("image", 105, "待修复图片")],
        [output(149, "image", "save image", "save preview")], minimum_run_seconds=30,
    ),
    workflow(
        "animate_transfer", "Animate 动作迁移 ProMax", "根据动作视频驱动人物并自动匹配尺寸",
        "video", "2087936157744189442", "reference_image",
        [input_field("motion_video", "动作视频", "video"), input_field("reference_image", "人物参考图")],
        [upload("motion_video", 275, "动作视频", "video", "choose video to upload"), upload("reference_image", 299, "人物参考图")],
        [output(500, "video", "save video", "save preview")], timeout=7200,
    ),
    workflow(
        "ltx23_hd_digital_human", "LTX 2.3 单图高清数字人", "根据人物图片和音频生成带口型与声音的高清数字人视频",
        "video", "2089711917068804098", "portrait",
        [input_field("portrait", "人物图片"), input_field("audio", "驱动音频", "audio")],
        [upload("portrait", 517, "人物图片"), upload("audio", 607, "驱动音频", "audio")],
        [output(140, "video", "save video", "save preview")], timeout=7200,
    ),
    workflow(
        "qwen_prompt_image", "Qwen3 反推提示词 + Z-Image", "从参考图反推提示词并重新生成高清图片",
        "image", "2087933748502417409", "reference",
        [input_field("reference", "参考图片")], [upload("reference", 100, "参考图片")],
        [output(161, "image", "save image", "save preview")], minimum_run_seconds=30,
    ),
    workflow(
        "scail_multi_reference", "极境 SCAIL2 动作迁移（多参考）", "使用动作视频和 6 张人物参考图生成动作迁移视频",
        "video", "2087945522677108738", "reference1",
        [input_field("motion_video", "动作视频", "video"), *[input_field(f"reference{i}", f"参考图 {i}") for i in range(1, 7)]],
        [upload("motion_video", 214, "动作视频", "video", "choose video to upload"), *[upload(f"reference{i}", node, f"参考图 {i}") for i, node in enumerate((1166, 1244, 1336, 1337, 1338, 1339), 1)]],
        [output(161, "video", "save video", "save preview")], timeout=7200,
    ),
    workflow(
        "scail_seven_outfit", "SCAIL 2 七段贴图换装", "使用动作视频和 7 张服装贴图生成七段换装视频",
        "video", "2087947462567874561", "outfit1",
        [input_field("motion_video", "动作视频", "video"), *[input_field(f"outfit{i}", f"第 {i} 段贴图") for i in range(1, 8)]],
        [upload("motion_video", 33, "动作视频", "video", "choose video to upload"), *[upload(f"outfit{i}", node, f"第 {i} 段贴图") for i, node in enumerate((30, 248, 461, 462, 464, 465, 466), 1)]],
        [output(670, "video", "save video", "save preview")], timeout=7200, minimum_run_seconds=0,
    ),
    workflow(
        "scail_4k_pose_background", "极境 4K 姿势迁移 · 背景替换", "将人物迁移到背景场景并增强姿势与画面一致性",
        "image", "2088160851734913026", "person",
        [input_field("background", "背景图"), input_field("person", "人物图"),
         input_field("prompt", "迁移要求", "text", "text")],
        [upload("background", 393, "背景图"), upload("person", 396, "人物图")],
        [output(391, "image", "save image", "save preview")],
        texts=[{"key": "prompt", "node_id": "424", "widget": "编辑文本", "label": "迁移要求", "required": True}],
        minimum_run_seconds=30,
    ),
    workflow(
        "krea2_realistic_4k", "Krea2 超写实 4K 文生图", "输入画面提示词，生成超写实 4K 图片",
        "image", "2088149025097863170", "prompt",
        [input_field("prompt", "画面提示词", "text", "text")], [],
        [output(83, "image", "save preview", "save image")],
        texts=[{"key": "prompt", "node_id": "64", "widget": "text", "label": "画面提示词", "required": True}],
        timeout=7200, minimum_run_seconds=30,
    ),
    workflow(
        "qwen_multi_view", "Qwen 角色三视图 · 多视角", "根据一张角色参考图生成多角度全身、半身和面部视图",
        "image", "2087934940880134146", "character",
        [input_field("character", "角色参考图")], [upload("character", 61, "角色参考图")],
        [output(448, "image", "save preview", "save image")], timeout=7200, minimum_run_seconds=30,
    ),
    workflow(
        "auto_storyboard_short_video", "自动分镜 · 短视频", "根据参考图和分镜数量及特写要求生成差异化短视频分镜图",
        "image", "2089754761372454913", "reference",
        [input_field("reference", "参考图"), input_field("request", "分镜数量与要求", "text", "text")],
        [upload("reference", 41, "参考图")],
        [output(114, "image", "save image", "save preview")],
        texts=[{"key": "request", "node_id": "127", "widget": "text", "label": "分镜数量与要求", "required": True}],
        timeout=7200, minimum_run_seconds=30,
    ),
    workflow(
        "firered_ecommerce_tryon", "极境电商换装 · FireRed", "根据人物图与服装参考图生成保持人物特征的电商换装效果",
        "image", "2089732224055861249", "person",
        [input_field("person", "人物图"), input_field("garment", "服装参考图"),
         input_field("prompt", "换装要求", "text", "text")],
        [upload("person", 207, "人物图"), upload("garment", 208, "服装参考图")],
        [output(253, "image", "save image", "save preview")],
        texts=[{"key": "prompt", "node_id": "264", "widget": "prompt", "label": "换装要求", "required": True}],
        timeout=7200, minimum_run_seconds=30,
    ),
    workflow(
        "minimax_h3_four_view", "MiniMax H3 辅助四视图生成", "根据一张角色图片生成面部近景及正面、侧面、背面四视图",
        "image", "2089783285118496770", "character",
        [input_field("character", "角色参考图")], [upload("character", 17, "角色参考图")],
        [output(5, "image", "save image", "save preview")], timeout=7200, minimum_run_seconds=30,
    ),
    workflow(
        "minimax_h3_dual_stage", "Minimax H3 二采重绘 V2", "上传图片并生成 Minimax H3 二次采样重绘视频",
        "video", "2089228867037913090", "source",
        [input_field("source", "输入图片"), input_field("prompt", "提示词", "text", "text")],
        [upload("source", 137, "输入图片")],
        [output(168, "video", "save video", "save preview")],
        texts=[{"key": "prompt", "node_id": "138", "widget": "value", "label": "提示词", "required": True}],
        timeout=7200,
    ),
    workflow(
        "seedvr2_upscale", "SeedVR2 万物高清放大", "上传图片并生成 SeedVR2 高清放大结果",
        "image", "2089614562243993601", "source",
        [input_field("source", "输入图片")], [upload("source", 15, "输入图片")],
        [output(101, "image", "save image", "save preview")], timeout=7200, minimum_run_seconds=30,
    ),
]

def workflow_catalog_response() -> dict:
    return {"version": 2, "default_workflow_key": DEFAULT_WORKFLOW_KEY, "workflows": WORKFLOW_CATALOG}
