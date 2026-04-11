import type { GameScript } from '../engine/types';

/**
 * Demo 脚本 — 用于测试引擎所有功能
 *
 * 功能覆盖：
 * - 多角色对话（dialogue）
 * - 旁白（narration）
 * - 内心独白（thought）
 * - 行内效果（角色进出场、立绘切换、背景切换）
 * - 选择分支（2条分支线）
 * - 场景转场
 */
export const demoScript: GameScript = {
  title: '月下庭园',
  author: 'Novel2Gal Demo',
  firstScene: 'prologue',
  scenes: {
    // ========== 序章 ==========
    prologue: {
      id: 'prologue',
      transition: 'fade',
      characters: [],
      lines: [
        {
          type: 'narration',
          text: '深秋的傍晚，落叶铺满了学院的石板路。',
        },
        {
          type: 'narration',
          text: '远处的钟楼敲响了五点的钟声，余音在暮色中缓缓散去。',
        },
        {
          type: 'narration',
          text: '一个身影独自站在庭园的长椅旁，似乎在等待什么人。',
          effects: [
            {
              type: 'show_character',
              payload: {
                id: 'yuki',
                name: '雪',
                sprite: '',
                position: 'center',
                isActive: false,
                flipped: false,
              },
            },
          ],
        },
      ],
      nextScene: 'garden_meeting',
    },

    // ========== 庭园相遇 ==========
    garden_meeting: {
      id: 'garden_meeting',
      transition: 'fade',
      characters: [
        { id: 'yuki', name: '雪', sprite: '', position: 'right', isActive: false, flipped: false },
      ],
      lines: [
        {
          type: 'thought',
          character: '主角',
          text: '是学姐……她怎么一个人在这里？',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '你来了。我还以为你忘记了我们的约定。',
        },
        {
          type: 'dialogue',
          character: '主角',
          text: '怎么会忘呢。学姐说的每一句话，我都记得清清楚楚。',
          effects: [
            {
              type: 'show_character',
              payload: {
                id: 'protagonist',
                name: '主角',
                sprite: '',
                position: 'left',
                isActive: true,
                flipped: false,
              },
            },
          ],
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '……你总是这样，说些让人不好意思的话。',
        },
        {
          type: 'narration',
          text: '学姐轻轻别过头，但我注意到她嘴角微微上扬。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '今天叫你来……其实是有件重要的事想跟你说。',
        },
        {
          type: 'thought',
          character: '主角',
          text: '重要的事？学姐的表情忽然变得认真起来，我的心跳莫名加速了。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '下个月……我就要毕业了。之后可能会去很远的地方。',
        },
        {
          type: 'narration',
          text: '空气仿佛凝固了一瞬。\n风吹过庭园，卷起几片落叶。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '所以，在那之前——',
        },
        {
          type: 'narration',
          text: '她停顿了一下，像是在鼓起勇气。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '你愿意……陪我去看最后一次月下庭园吗？就是学院后山那个。',
        },
      ],
      choices: [
        {
          text: '当然愿意。不管多少次，只要是学姐的请求。',
          targetScene: 'accept_path',
        },
        {
          text: '……为什么偏偏要和我去？',
          targetScene: 'question_path',
        },
      ],
    },

    // ========== 分支A：欣然接受 ==========
    accept_path: {
      id: 'accept_path',
      transition: 'dissolve',
      lines: [
        {
          type: 'dialogue',
          character: '主角',
          text: '当然愿意。不管多少次，只要是学姐的请求。',
        },
        {
          type: 'narration',
          text: '学姐愣了一下，随即绽放出我从未见过的笑容。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '谢谢你……果然找你是对的。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '那就说好了，这个周末，晚上八点。\n我在后山入口等你。',
        },
        {
          type: 'thought',
          character: '主角',
          text: '她的笑容，就像月光一样温柔。\n我在心里悄悄许下了一个约定。',
        },
      ],
      nextScene: 'epilogue_good',
    },

    // ========== 分支B：追问原因 ==========
    question_path: {
      id: 'question_path',
      transition: 'fade',
      lines: [
        {
          type: 'dialogue',
          character: '主角',
          text: '……为什么偏偏要和我去？',
        },
        {
          type: 'narration',
          text: '学姐的表情微微一变，像是没料到我会这样问。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '……你果然还是这么迟钝。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '因为——那个庭园，是我们第一次说话的地方啊。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '你不记得了吗？一年前的秋天，你在后山迷了路。\n是我带你走出来的。',
        },
        {
          type: 'thought',
          character: '主角',
          text: '……那个时候的事。\n原来学姐一直记着。',
        },
        {
          type: 'dialogue',
          character: '主角',
          text: '我记得。那天的月光很亮，学姐的背影——我从来没忘过。',
        },
        {
          type: 'dialogue',
          character: '雪',
          text: '……笨蛋。\n那你就更应该来了吧？',
        },
        {
          type: 'narration',
          text: '学姐红着脸转过身去。\n但我看到她的肩膀轻轻颤抖，像是在忍住笑意。',
        },
      ],
      nextScene: 'epilogue_good',
    },

    // ========== 结局 ==========
    epilogue_good: {
      id: 'epilogue_good',
      transition: 'blackout',
      lines: [
        {
          type: 'narration',
          text: '那一天，秋日的庭园里，两个人之间的距离悄然缩短了。',
        },
        {
          type: 'narration',
          text: '或许命运的齿轮，从这一刻开始转动。',
        },
        {
          type: 'narration',
          text: '—— 序章 · 完 ——',
        },
        {
          type: 'narration',
          text: '感谢体验 Novel2Gal 引擎 Demo！\n\n这个演示展示了：对话、旁白、内心独白、选择分支、场景转场等核心功能。',
        },
      ],
    },
  },
};
