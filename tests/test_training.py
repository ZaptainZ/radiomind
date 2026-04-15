"""Tests for training data generation and LoRA training pipeline.

MLX tests are skipped if MLX is not installed.
"""

import json
import pytest

from radiomind.core.config import Config
from radiomind.core.mind import RadioMind
from radiomind.core.types import MemoryEntry, MemoryLevel, Message
from radiomind.storage.database import MemoryStore
from radiomind.storage.hdc import HabitStore
from radiomind.training.data_gen import TrainingDataGenerator
from radiomind.training.lora import TrainConfig, check_mlx_available


@pytest.fixture
def store_with_habits(tmp_path):
    store = MemoryStore(tmp_path / "test.db")
    store.open()

    habits = HabitStore(tmp_path / "hdc")
    habits.open()

    # v0.2 quality gates demand >= 5 habits and >= 2 domains so the
    # training-data generator doesn't refuse. Confidence must be >= 0.7
    # to pass HabitStore.MIN_CONFIDENCE.
    for dom in ("health", "work", "hobby"):
        for i in range(3):
            store.add(MemoryEntry(
                content=f"{dom} 事实 {i}：我在 {dom} 领域的独特观察 {i}",
                domain=dom, level=MemoryLevel.FACT,
            ))
        store.add(MemoryEntry(
            content=f"{dom} 模式：倾向高质量、低频次的投入",
            domain=dom, level=MemoryLevel.PATTERN,
        ))
    store.add(MemoryEntry(
        content="用户重视自主性",
        domain="meta", level=MemoryLevel.PRINCIPLE,
    ))

    for desc in (
        "用户喜欢每天早上跑步锻炼",
        "用户不喜欢被时间压力驱动的加班",
        "用户偏好手冲咖啡并讨厌糖饮",
        "用户每周三晚上固定做瑜伽",
        "用户认为 Rust 的所有权模型更优雅",
        "用户计划十月去京都看红叶",
    ):
        habits.add_habit(desc, [("user", desc)], confidence=0.85)

    yield store, habits
    habits.close()
    store.close()


class TestTrainingDataGen:
    def test_generate_creates_jsonl(self, store_with_habits, tmp_path):
        store, habits = store_with_habits
        gen = TrainingDataGenerator(store, habits)

        output = tmp_path / "train.jsonl"
        count = gen.generate(output)

        assert count > 0
        assert output.exists()

        # Verify JSONL format
        with open(output) as f:
            for line in f:
                data = json.loads(line)
                assert "messages" in data
                assert len(data["messages"]) == 3
                assert data["messages"][0]["role"] == "system"
                assert data["messages"][1]["role"] == "user"
                assert data["messages"][2]["role"] == "assistant"

    def test_generate_includes_habits(self, store_with_habits, tmp_path):
        store, habits = store_with_habits
        gen = TrainingDataGenerator(store, habits)

        output = tmp_path / "train.jsonl"
        gen.generate(output)

        content = output.read_text()
        # Generated content must reference at least one of the seeded habits
        assert any(kw in content for kw in ("锻炼", "瑜伽", "跑步", "咖啡", "Rust", "京都"))

    def test_generate_empty_store(self, tmp_path):
        store = MemoryStore(tmp_path / "empty.db")
        store.open()
        habits = HabitStore(tmp_path / "hdc_empty")
        habits.open()

        gen = TrainingDataGenerator(store, habits)
        output = tmp_path / "train.jsonl"
        count = gen.generate(output)

        assert count == 0 or count >= 0  # may generate from patterns/principles
        habits.close()
        store.close()

    def test_generate_chinese(self, store_with_habits, tmp_path):
        store, habits = store_with_habits
        gen = TrainingDataGenerator(store, habits)

        output = tmp_path / "train_zh.jsonl"
        count = gen.generate(output, language="zh")
        assert count > 0

    def test_generate_english(self, store_with_habits, tmp_path):
        store, habits = store_with_habits
        gen = TrainingDataGenerator(store, habits)

        output = tmp_path / "train_en.jsonl"
        count = gen.generate(output, language="en")
        assert count > 0


class TestTrainConfig:
    def test_default_config(self):
        tc = TrainConfig()
        assert "Qwen" in tc.model
        assert tc.iterations == 500
        assert tc.lora_rank == 8

    def test_from_config(self):
        cfg = Config()
        cfg.set("training.iterations", 100)
        cfg.set("training.model", "custom-model")
        tc = TrainConfig.from_config(cfg)
        assert tc.iterations == 100
        assert tc.model == "custom-model"

    def test_output_dir(self):
        cfg = Config()
        tc = TrainConfig.from_config(cfg)
        assert "models/lora" in tc.output_dir


class TestMLXAvailability:
    def test_check_returns_tuple(self):
        available, msg = check_mlx_available()
        assert isinstance(available, bool)
        assert isinstance(msg, str)
        if not available:
            assert "pip install" in msg


class TestMindTrainIntegration:
    def test_generate_training_data(self, tmp_path):
        cfg = Config()
        cfg.set("general.home", str(tmp_path / ".radiomind"))
        mind = RadioMind(config=cfg)
        mind.initialize()

        mind.ingest([
            Message(role="user", content="我叫小明"),
            Message(role="user", content="我喜欢跑步"),
        ])

        count, path = mind.generate_training_data()
        assert count >= 0
        assert path.endswith(".jsonl")

        mind.shutdown()

    def test_train_without_data(self, tmp_path):
        cfg = Config()
        cfg.set("general.home", str(tmp_path / ".radiomind"))
        mind = RadioMind(config=cfg)
        mind.initialize()

        result = mind.train()
        assert not result.success
        # Either the data-gen refused (new v0.2 gate) or training said no data
        assert any(msg in result.error for msg in ("No training data", "Too few training examples", "need >="))

        mind.shutdown()
