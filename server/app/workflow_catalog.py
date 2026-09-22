"""Server-owned RunningHub workflow catalog delivered to licensed clients."""

DEFAULT_WORKFLOW_KEY = "person_replace"

OOTD_DEFAULT_PROMPTS = (
    "帮我基于这张图片生成视频。镜头采用中景固定镜头，平视角度。她先是单手轻抚脸颊，"
    "摆出优雅的姿势，随后眼神直视镜头，露出自信迷人的微笑，右手轻轻抬起致意。"
    "画面无模糊，真实写实风格，无多余特效。",
    "帮我基于这张图片生成视频，镜头依然是平视中景。她微笑着向镜头挥手，随后双手拿起"
    "一件折叠好的白色衣物展示给顾客（镜头），动作流畅自然，充满亲和力画面无模糊，"
    "真实写实风格，无多余特效。",
    "帮我基于这张图片生成视频，她站在收银台前，双手在操作台面上忙碌，似乎在整理单据"
    "或操作收银设备，头部微微低垂，神情专注。随后她抬起头，视线扫过镜头。镜头保持固定，"
    "捕捉了她工作的瞬间。，画面无模糊，真实写实风格，无多余特效。",
    "帮我基于这张图片生成视频，她面带微笑，右手轻轻触碰面前的平板电脑屏幕，似乎在输入"
    "信息或结账。镜头依然是平视中景，聚焦于她的上半身和手部动作。她的神态温柔亲切，"
    "与观众建立眼神交流。，画面无模糊，真实写实风格，无多余特效。",
    "帮我基于这张图片生成视频，她先是微笑着向镜头挥手打招呼，然后转身伸手从身后的衣架上"
    "取下一件白色的衬衫，将其展开向镜头展示。镜头跟随她的动作进行轻微的平移，捕捉她从"
    "“店主”到“导购”的角色转换。画面无模糊，真实写实风格，无多余特效。",
    "帮我基于这张图片生成视频，女子右手搭在平板边缘.美学控制：固定镜头，中近景中心构图，"
    "光线柔和自然，保留原图色调，符合现实物理逻辑。风格化：真实感写实风格，画面清晰无模糊，"
    "自然且富有生活气息。",
    "帮我基于这张图片生成视频，女子拿起水杯喝水美学控制：固定镜头，中近景中心构图，"
    "光线柔和自然，保留原图色调，符合现实物理逻辑。风格化：真实感写实风格，画面清晰无模糊，"
    "自然且富有生活气息。",
)

SCAIL_4K_DEFAULT_PROMPT = (
    "将图1中的角色移至图2中，并调整为与图2角色相似的姿势。保持图1角色的外貌特征一致性，"
    "重新进行光线处理，使其与图2场景的光线和整体氛围自然融合，确保无明显人工痕迹。"
)

KREA2_DEFAULT_PROMPT = (
    "（电影级面光：1.6），（光线追踪：1.5），（冷白皮漫感质感的光滑皮肤：1.7），"
    "（人物有最好的骨相：1.2），（网感脸：1.6），身材完美，莫兰迪配色，高颜值网红，"
    "INS风，19岁女生尖下巴，三庭五眼比例均衡，细腻陶瓷水嫩肌肤，偏冷白皮，随机的妆容，"
    "随机的饰品，随机的动作，侧光，发丝轻飘，凌乱，随机角度拍摄，总体有很多的不确定性，"
    "但又好看， 氛围慵懒俏皮，东方美女，冷白皮气质美女，薇薇纯欲风，皮肤白皙，偶像气质，"
    "fairskin，气质的江南美女子，有点甜美，皮肤美白透亮，甜美氛围，细腻笔触，独特韵味的美，"
    "可爱表情，正面照，人物上半身特写，冷白皮，高清图 氛围感，目光看向一旁，电影级打光 。"
    "精致美女肖像，中长发，皮肤细腻光滑，妆容淡雅清新，俏皮可爱，突出自然美感 。空灵的气氛，"
    "巧妙地捕捉情感，杰作，柔和，高分辨率，景深构图，层次32k高清蓝光。 正面照，人物上半身"
    "特写镜头，身穿蓝色印花旗袍。披肩长卷发，蓝鲜花头饰，手拿同色系折扇。最高等级画质，IHD，"
    "美颜全开，超高清，32k分辨率，去掉一切噪点，户外背景。"
)

STORYBOARD_DEFAULT_PROMPT = "12，包含一个手部特写"
FIRERED_DEFAULT_PROMPT = (
    "让图1的人物穿上图2人物身上的衣服，不要改变发型，头发保持长发"
)

MINIMAX_H3_DEFAULT_PROMPT = """ subject_definitions:
<Subject 1> is the same young adult Chinese female fashion model defined consistently across <Picture 1>, <Picture 2>, and <Picture 3>. Preserve her exact facial identity, natural makeup, long black hair, slender body proportions, confident runway posture, and recognizable gaze throughout every shot.

Look A is defined by <Picture 1>: a white satin cowl-neck handkerchief top with slim chain straps and an open tie-back, loose black wide-leg cargo trousers, silver chain belt, silver necklace, light cream shoulder bag, and black pointed shoes.

Look B is defined by <Picture 2>: a white futuristic cutout bodysuit, loose white cargo trousers, white platform sneakers, silver handbag, large silver hoop earrings, layered silver necklaces, silver arm cuff, and silver wristwatch.

Look C is defined by <Picture 3>: a black knit crop top with a heart-shaped cutout, black leather jacket resting off the shoulders, distressed black shorts, sheer black tights, black pointed high-heeled ankle boots, black handbag, and black heart pendant.

<Environment 1> is the surreal minimalist runway defined by <Picture 4>: a long central black mirror runway inside a boundaryless dark space, symmetrical transparent vertical panels, thin cold-white, soft-pink, and champagne-gold light frames, a distant warm-white rectangular portal, subtle mist, strong one-point perspective, and precise reflections across the glossy floor.

summary:
[reference generation] An eight-second photorealistic high-fashion runway film featuring the same model in three complete outfits. She continuously advances along <Environment 1> while low-angle tracking, lateral sweeps, rising camera movement, and a final portrait push-in showcase Look A, Look B, and Look C. A full-frame trouser-leg occlusion and a vertical light-curtain occlusion trigger two seamless outfit transformations while preserving her identity, foot placement, walking direction, body momentum, hair movement, and runway position. The sequence ends in a commanding close-up in Look C.

retention_analysis:
<Subject 1> (appears in [Shot 1], [Shot 2], [Shot 3], and [Shot 4]): fully_preserved - preserve the same face, long black hair, makeup, anatomy, proportions, gaze, runway posture, and walking identity. Each outfit, shoe set, handbag, jewelry set, and accessory configuration transforms as one complete coordinated look only during its designated full-frame occlusion.

<Environment 1> (appears in [Shot 1], [Shot 2], [Shot 3], and [Shot 4]): fully_preserved - maintain the central black mirror runway, distant rectangular portal, symmetrical transparent panels, vertical light frames, subtle mist, boundaryless dark space, one-point perspective, and precise floor reflections throughout the video.

detailed_description:
[Shot 1] A low-angle wide camera glides rapidly forward just above the central black mirror runway of <Environment 1>, defined by <Picture 4>. The distant warm-white rectangular portal illuminates on the first bass impact, producing a centered reflection. <Subject 1> appears inside the portal in Look A, defined by <Picture 1>.

From 00:00.400 to 00:02.500, the camera reverses into a smooth backward tracking shot while maintaining a low-angle full-body composition. She raises her chin slightly and completes two confident crossover runway steps. Her right hand rests briefly inside the cargo-trouser pocket while the light cream shoulder bag remains balanced on her left shoulder. The white satin top develops soft flowing highlights; the silver waist chain and wide black trouser legs move naturally with her steps.

At 00:01.400, the camera sweeps quickly toward her right side and settles into a forty-five-degree medium-full tracking view. She turns one shoulder toward the lens, removes her right hand from the pocket, touches the silver waist chain once with her fingertips, and lowers her hand beside her body.

At 00:02.200, one wide black trouser leg swings across the low foreground until its dark fabric fills the complete frame.

[Shot 2] At 00:02.500, the trouser-leg occlusion clears to reveal <Subject 1> in Look B, defined by <Picture 2>. Her face, planted foot, body weight, forward speed, and walking axis continue seamlessly from the preceding action. The vertical frames of <Environment 1> brighten into cold silver-white light.

The shot begins as a low close-up of her white platform sneaker landing on a strong beat, with the shoe and loose trouser leg reflected across the mirror floor. The camera rises rapidly along her body into a frontal medium shot while she completes another crossover step.

She carries the silver handbag in her right hand and traces the side cutout of the bodysuit once with her left fingertips. Her chin rises slightly as she directs a cool, confident gaze toward the lens.

At 00:03.600, the camera arcs quickly toward her right side. She turns with the moving camera and lifts the silver handbag outward once, presenting its metallic surface and complete silhouette. At 00:04.300, a cold-white vertical light frame passes across her body and expands into a bright full-frame light curtain.

[Shot 3] At 00:04.600, the light curtain clears to reveal <Subject 1> in Look C, defined by <Picture 3>. Her facial identity, planted foot, body momentum, hair direction, and central runway position remain continuous. The environment shifts to obsidian black with sharp cold-white light cuts and restrained soft-pink accents along the outer panels.

The camera begins in a slightly canted medium-close view and retreats rapidly into a medium-full tracking composition. She advances with two assertive crossover steps. Her right hand carries the black handbag while her left hand supports the leather-jacket collar resting off her shoulder. Moving light reveals the leather folds, metal zipper, sheer tights, distressed shorts, and pointed ankle boots.

At 00:05.700, she sends her left shoulder toward the lens and flicks the leather jacket backward once. The jacket hem opens with natural weight and settles around her arms while the camera snaps laterally into a low side-tracking view.

At 00:06.500, her right boot lands on a strong beat at the front of the runway. She transfers her weight onto the rear leg, extends the front leg in a restrained crossover stance, places her left hand into the shorts pocket, and stops the black handbag beside her right leg, forming a powerful forty-five-degree runway pose.

[Shot 4] At 00:06.800, the camera performs a fast, controlled quarter-circle orbit around <Subject 1> and then pushes smoothly from a medium-full view into a close portrait. She lightly supports the leather-jacket collar at her left shoulder, turns her face toward the moving lens, raises her chin slightly, and fixes the camera with a cool, self-assured, commanding expression.

At 00:07.300, the camera settles into the close-up. Cold-white, champagne-gold, and soft-pink vertical frames illuminate sequentially behind her while the distant rectangular portal grows brighter. Each light forms a clean symmetrical reflection across the black mirror runway.

From 00:07.600 to 00:08.000, the camera holds the final portrait. Her facial identity, natural skin texture, long black hair, eye highlights, black heart pendant, leather collar, and calm commanding gaze remain sharply defined as the final bass tail resolves.

overall_soundscape:
A vast, clean runway interior with restrained spatial reverberation. Look A produces soft satin movement, heavier wide-leg trouser rustling, a delicate silver-chain sound, and precise pointed-shoe footfalls. Look B produces light technical-fabric folds, synchronized platform-sneaker impacts, and a restrained metallic handbag accent. Look C produces crisp leather folding, subtle zipper movement, soft tights friction, controlled handbag hardware sounds, and sharp pointed-boot impacts. The acoustic space remains focused on the model, footsteps, clothing, and accessories.

non_diegetic_music:
A polished 126 BPM beat-synchronized fashion electronic track built from deep bass impacts, minimal digital pulses, short metallic syncopations, and wide spatial synthesizers. Look A uses restrained monochrome pulses with warm metallic accents; Look B shifts into brighter cold-silver electronic tones; Look C introduces deeper, stronger bass and sharper rhythmic cuts.

Every footfall, camera sweep, clothing gesture, handbag presentation, and outfit transformation aligns with a distinct beat. Strong impacts mark the transformations at 00:02.500 and 00:04.600. The low-frequency rhythm intensifies at 00:06.800, the strongest accent drives the portrait push-in at 00:07.300, and the music resolves at exactly 00:08.000 with one short, clean bass tail."""


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


def input_field(key, label, media_type="image", input_type=None, *,
                required=True, default=None, required_when=None,
                minimum=None, maximum=None, step=None):
    item = {
        "key": key,
        "label": label,
        "media_type": input_type or media_type,
    }
    if input_type:
        item["input_type"] = input_type
    if not required:
        item["required"] = False
    if default is not None:
        item["default"] = default
    if required_when:
        item["required_when"] = required_when
    if minimum is not None:
        item["min"] = minimum
    if maximum is not None:
        item["max"] = maximum
    if step is not None:
        item["step"] = step
    return item


def workflow(key, name, description, category, post_id, primary_input,
             inputs, uploads, outputs, *, texts=None, widgets=None,
             node_modes=None, timeout=3000,
             minimum_run_seconds=300, ignore_task_failure=False):
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
            "widgets": widgets or [],
            "node_modes": node_modes or [],
            "outputs": outputs,
            "completion": {
                "markers": ["显示报告", "Show Report"],
                "minimum_run_seconds": minimum_run_seconds,
                "ignore_task_failure": ignore_task_failure,
            },
            "strict_outputs": True,
        },
    }


WORKFLOW_CATALOG = [
    workflow(
        "person_replace", "人物替换", "使用替换背景、参考人物与动作视频生成",
        "video", "2087949278193995777", "model",
        [
            input_field(
                "upload_background", "上传替换背景", input_type="boolean",
                default=True,
            ),
            input_field(
                "background", "替换背景图", required=False,
                required_when={"key": "upload_background", "equals": True},
            ),
            input_field("video", "动作视频", "video"),
            input_field("model", "人物参考图"),
        ],
        [
            upload("background", 247, "替换背景图", required=False),
            upload("model", 108, "人物参考图"),
            upload(
                "video", 112, "动作视频", "video", "choose video to upload"
            ),
        ],
        [output(119, "video", "save video", "save preview")],
        widgets=[{
            "key": "upload_background", "node_id": "250",
            "widget": "RGTHREE_TOGGLE_AND_NAV", "label": "上传替换背景",
            "true_value": True, "false_value": False, "required": True,
            "default": True,
            "interaction": "rgthree_toggle",
        }],
    ),
    workflow(
        "ootd_7day", "OOTD 7天变装", "7 张穿搭图片生成并合成长视频",
        "video", "2087951298946752514", "day1",
        [
            *[
                field
                for day in range(1, 8)
                for field in (
                    input_field(f"day{day}", f"第 {day} 天图片"),
                    input_field(
                        f"prompt{day}", f"第 {day} 天动作提示词",
                        "text", "text", default=OOTD_DEFAULT_PROMPTS[day - 1],
                    ),
                )
            ],
            input_field("audio", "背景音乐", "audio"),
        ],
        [*[upload(f"day{day}", node, f"第 {day} 天图片") for day, node in enumerate((6557, 6798, 6851, 7110, 7170, 7786, 7852), 1)], upload("audio", 6726, "背景音乐", "audio")],
        [output(6223, "video", "save video", "save preview")],
        texts=[
            {
                "key": f"prompt{day}", "node_id": str(node_id),
                "widget": "text", "label": f"第 {day} 天动作提示词",
                "required": True,
            }
            for day, node_id in enumerate(
                (7583, 7614, 7645, 7676, 7707, 7819, 7855), 1
            )
        ],
        timeout=7200,
    ),
    workflow(
        "animate_transfer", "Animate 动作迁移 ProMax", "根据动作视频驱动人物并自动匹配尺寸",
        "video", "2087936157744189442", "reference_image",
        [
            input_field("motion_video", "动作视频", "video"),
            input_field("reference_image", "人物参考图"),
            input_field(
                "motion_strength", "动作幅度（节点 266）",
                input_type="number", default=0.2, minimum=0, step=0.01,
            ),
            input_field(
                "frame_load_cap", "加载帧数上限（节点 422）",
                input_type="integer", default=900, minimum=1, step=1,
            ),
        ],
        [upload("motion_video", 275, "动作视频", "video", "choose video to upload"), upload("reference_image", 299, "人物参考图")],
        [output(500, "video", "save video", "save preview")],
        widgets=[
            {
                "key": "motion_strength", "node_id": "266",
                "widget": "value", "label": "动作幅度",
                "value_type": "number", "default": 0.2,
            },
            {
                "key": "frame_load_cap", "node_id": "422",
                "widget": "value", "label": "加载帧数上限",
                "value_type": "integer", "default": 900,
            },
        ],
        timeout=7200,
    ),
    workflow(
        "ru_dance_motion_expression", "Ru摇+动作迁移+表情控制+消除泛黄【升级版】",
        "动作迁移、表情控制并减少画面泛黄、脸型偏移和变色",
        "video", "2099868007005769729", "reference_image",
        [
            input_field("motion_video", "视频输入", "video"),
            input_field("reference_image", "图像输入"),
            input_field(
                "jitter", "抖动（节点 1009）",
                input_type="number", default=0.2, minimum=0, step=0.01,
            ),
            input_field(
                "custom_width", "自定义宽度（节点 966）",
                input_type="integer", default=720, minimum=0, step=1,
            ),
            input_field(
                "custom_height", "自定义高度（节点 967）",
                input_type="integer", default=1280, minimum=0, step=1,
            ),
        ],
        [
            upload(
                "motion_video", 413, "视频输入", "video",
                "choose video to upload",
            ),
            upload("reference_image", 57, "图像输入"),
        ],
        [output(867, "video", "save video", "save preview")],
        widgets=[{
            "key": "jitter", "node_id": "1009",
            "widget": "value", "label": "抖动",
            "value_type": "number", "default": 0.2,
        }, {
            "key": "custom_width", "node_id": "966",
            "widget": "value", "label": "自定义宽度",
            "value_type": "integer", "default": 720,
        }, {
            "key": "custom_height", "node_id": "967",
            "widget": "value", "label": "自定义高度",
            "value_type": "integer", "default": 1280,
        }],
        timeout=7200,
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
        "hd_restore_detail_v2", "高定版高清修复【去AI感加细节】洗图",
        "上传一张图片，去除 AI 感并增强细节，输出高清修复图",
        "image", "2087951445663510530", "source",
        [input_field("source", "原始图片")], [upload("source", 105, "原始图片")],
        [output(149, "image", "save image", "save preview")], minimum_run_seconds=30,
    ),
    workflow(
        "scail_multi_reference", "极境 SCAIL2 动作迁移（多参考）",
        "使用动作视频和 2 张人物参考图生成动作迁移视频",
        "video", "2087945522677108738", "reference1",
        [
            input_field("motion_video", "动作视频", "video"),
            input_field("reference1", "参考图 1"),
            input_field("reference2", "参考图 2"),
        ],
        [
            upload(
                "motion_video", 214, "动作视频", "video",
                "choose video to upload",
            ),
            upload("reference1", 1166, "参考图 1"),
            upload("reference2", 1244, "参考图 2"),
        ],
        [output(161, "video", "save video", "save preview")],
        node_modes=[
            *[
                {"node_id": str(node_id), "mode": 2,
                 "label": f"参考图节点 {node_id}"}
                for node_id in (1336, 1337, 1338, 1339)
            ],
            *[
                {"node_id": str(node_id), "mode": 4,
                 "label": f"图片拼接节点 {node_id}"}
                for node_id in (1340, 1341, 1342, 1343)
            ],
        ],
        timeout=7200,
    ),
    workflow(
        "scail_seven_outfit", "SCAIL 2 七段贴图换装", "使用动作视频和 7 张服装贴图生成七段换装视频",
        "video", "2087947462567874561", "outfit1",
        [input_field("motion_video", "动作视频", "video"), *[input_field(f"outfit{i}", f"第 {i} 段贴图") for i in range(1, 8)]],
        [upload("motion_video", 33, "动作视频", "video", "choose video to upload"), *[upload(f"outfit{i}", node, f"第 {i} 段贴图") for i, node in enumerate((30, 248, 461, 462, 464, 465, 466), 1)]],
        [output(670, "video", "save video", "save preview")], timeout=7200, minimum_run_seconds=0,
    ),
    workflow(
        "scail_4k_pose_background", "极境 4K 姿势迁移 · 背景替换", "将图1中的角色移至图2中，并调整为与图2角色相似的姿势。保持图1角色的外貌特征一致性，重新进行光线处理，使其与图2场景的光线和整体氛围自然融合，确保无明显人工痕迹。",
        "image", "2088160851734913026", "person",
        [input_field("background", "背景图"), input_field("person", "人物图"),
         input_field(
             "prompt", "迁移要求", "text", "text",
             default=SCAIL_4K_DEFAULT_PROMPT,
         )],
        [upload("background", 393, "背景图"), upload("person", 396, "人物图")],
        [output(391, "image", "save image", "save preview")],
        texts=[{"key": "prompt", "node_id": "424", "widget": "编辑文本", "label": "迁移要求", "required": True}],
        minimum_run_seconds=30,
    ),
    workflow(
        "krea2_realistic_4k", "Krea2 超写实 4K 文生图", "输入画面提示词，生成超写实 4K 图片",
        "image", "2088149025097863170", "prompt",
        [input_field(
            "prompt", "画面提示词", "text", "text",
            default=KREA2_DEFAULT_PROMPT,
        )], [],
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
        "auto_storyboard_short_video", "自动分镜 · 短视频", "12，包含一个手部特写",
        "image", "2089754761372454913", "reference",
        [
            input_field("reference", "参考图"),
            input_field(
                "request", "分镜数量与要求", "text", "text",
                default=STORYBOARD_DEFAULT_PROMPT,
            ),
        ],
        [upload("reference", 41, "参考图")],
        # Match Qwen multi-view's preview-first batch download path. The
        # generic Save Image action can save only the selected frame, whereas
        # Save Preview can be invoked for every generated thumbnail.
        [output(114, "image", "save preview", "save image")],
        texts=[{"key": "request", "node_id": "127", "widget": "text", "label": "分镜数量与要求", "required": True}],
        timeout=7200, minimum_run_seconds=30,
    ),
    workflow(
        "firered_ecommerce_tryon", "极境电商换装 · FireRed", "让图1的人物穿上图2人物身上的衣服，不要改变发型，头发保持长发",
        "image", "2089732224055861249", "person",
        [input_field("person", "人物图"), input_field("garment", "服装参考图"),
         input_field(
             "prompt", "换装要求", "text", "text",
             default=FIRERED_DEFAULT_PROMPT,
         )],
        [upload("person", 207, "人物图"), upload("garment", 208, "服装参考图")],
        [output(253, "image", "save image", "save preview")],
        texts=[{"key": "prompt", "node_id": "264", "widget": "编辑文本", "label": "换装要求", "required": True}],
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
        [
            input_field("source", "输入图片"),
            input_field(
                "prompt", "提示词", "text", "text",
                default=MINIMAX_H3_DEFAULT_PROMPT,
            ),
        ],
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
    return {"version": 5, "default_workflow_key": DEFAULT_WORKFLOW_KEY, "workflows": WORKFLOW_CATALOG}
