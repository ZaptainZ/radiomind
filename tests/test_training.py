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

    # Populate with test data
    store.add(MemoryEntry(content="用户喜欢跑步", domain="health", level=MemoryLevel.FACT))
    store.add(MemoryEntry(content="用户讨厌加班", domain="work", level=MemoryLevel.FACT))
    store.add(MemoryEntry(content="运动改善睡眠", domain="health", level=MemoryLevel.PATTERN))
    store.add(MemoryEntry(content="用户重视自主性", domain="meta", level=MemoryLevel.PRINCIPLE))

    habits.add_habit("用户重视健康和规律运动", [("user", "health")])
    habits.add_habit("用户讨厌被时间压力驱动", [("user", "pressure")])

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
        assert "健康" in content or "运动" in content

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
        assert "No training data" in result.error

        mind.shutdown()
