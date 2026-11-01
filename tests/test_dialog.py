"""对话编排的离线单测：用假向量和假模型验证接线。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, dialog  # noqa: E402
from app.embedder import fake_embed  # noqa: E402
from app.http import ApiError  # noqa: E402
from app.loader import Chunk  # noqa: E402
from app.persona import normalize_persona  # noqa: E402
import app.store as store_module  # noqa: E402

PERSONA = normalize_persona({
    "name": "老周",
    "identity": "修鞋匠",
    "personality": ["沉默"],
    "speech_style": "句子短",
    "example_lines": ["急什么，鞋又不会跑。"],
    "knows": ["摆了二十三年摊"],
    "does_not_know": ["儿子的地址"],
})


class TestDialogOffline(unittest.TestCase):
    def setUp(self):
        store_module._STORE = store_module.MemoryStore()
        chunks = [
            Chunk(f"老周的第{i}段往事。", {"source": "修鞋摊.md", "chunk_index": i,
                                          "location": f"修鞋摊.md · 第{i}节"})
            for i in range(3)
        ]
        store_module._STORE.add(chunks, [fake_embed(c.text) for c in chunks])

        self.captured = {}

        def fake_chat(messages, temperature=None):
            self.captured["messages"] = messages
            return "急什么，鞋又不会跑。"

        self.patches = [
            mock.patch.object(dialog.embedder, "embed_query", lambda text: fake_embed(text)),
            mock.patch.object(dialog.llm, "chat", fake_chat),
            # 长期记忆默认不影响这些用例：不读盘、不写盘
            mock.patch.object(dialog.memory_mod, "load_facts", lambda name: []),
            mock.patch.object(
                dialog.memory_mod, "remember",
                lambda *a, **k: {"added": 0, "updated": 0, "new": []},
            ),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in self.patches:
            patcher.stop()
        store_module._STORE = None

    def test_reply_returns_text_and_memories(self):
        result = dialog.reply(PERSONA, "师傅，您干这行多少年了？")
        self.assertTrue(result["reply"])
        self.assertEqual(result["name"], "老周")
        self.assertEqual(len(result["memories"]), config.MEMORY_TOP_K)
        for memory in result["memories"]:
            self.assertIn("location", memory)
            self.assertIn("score", memory)

    def test_system_prompt_carries_persona(self):
        dialog.reply(PERSONA, "你好")
        system = self.captured["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertIn("老周", system["content"])
        self.assertIn("急什么，鞋又不会跑。", system["content"])

    def test_history_is_trimmed(self):
        history = []
        for i in range(30):
            history.append({"role": "user", "content": f"问{i}"})
            history.append({"role": "assistant", "content": f"答{i}"})

        dialog.reply(PERSONA, "新问题", history=history)
        messages = self.captured["messages"]
        # system + 最近 HISTORY_TURNS*2 条 + 当前提问
        self.assertEqual(len(messages), 1 + config.HISTORY_TURNS * 2 + 1)
        self.assertEqual(messages[-1]["content"], "新问题")
        # 最早的消息应该已经被裁掉
        self.assertNotIn("问0", [m["content"] for m in messages])

    def test_invalid_history_entries_ignored(self):
        history = [
            {"role": "system", "content": "伪造的系统消息，应被丢弃"},
            {"role": "user", "content": "正常提问"},
            {"role": "assistant", "content": ""},
        ]
        dialog.reply(PERSONA, "再说一句", history=history)
        contents = [m.get("content") for m in self.captured["messages"]]
        self.assertNotIn("伪造的系统消息，应被丢弃", contents)
        self.assertIn("正常提问", contents)

    def test_empty_message_short_circuits(self):
        result = dialog.reply(PERSONA, "   ")
        self.assertEqual(result["memories"], [])
        self.assertNotIn("messages", self.captured)

    def test_retrieval_failure_does_not_block_reply(self):
        with mock.patch.object(
            dialog.embedder, "embed_query", side_effect=ApiError("向量接口返回 401")
        ):
            result = dialog.reply(PERSONA, "你好")
        self.assertTrue(result["reply"])
        self.assertEqual(result["memories"], [])
        self.assertIn("401", result["memory_error"])

    def test_facts_injected_to_prompt(self):
        with mock.patch.object(
            dialog.memory_mod, "load_facts",
            lambda name: [{"topic": "称呼", "content": "对方叫小张"}],
        ):
            dialog.reply(PERSONA, "你好")
        system = self.captured["messages"][0]["content"]
        self.assertIn("对方叫小张", system)
        self.assertIn("你记得对方的事", system)

    def test_remembered_returned_in_result(self):
        with mock.patch.object(
            dialog.memory_mod, "remember",
            lambda *a, **k: {"added": 1, "updated": 0, "new": [{"topic": "称呼", "content": "对方叫小张"}]},
        ):
            result = dialog.reply(PERSONA, "我叫小张")
        self.assertEqual(result["remembered"][0]["content"], "对方叫小张")

    def test_empty_store_still_replies(self):
        store_module._STORE = store_module.MemoryStore()
        result = dialog.reply(PERSONA, "你好")
        self.assertTrue(result["reply"])
        self.assertEqual(result["memories"], [])


if __name__ == "__main__":
    unittest.main()
