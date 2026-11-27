import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from etl.models import DataType, PipelineItem
from etl.pipeline.base import Pipeline


class TestPipelineInit:
    def test_init_stores_ingest_sequence(self):
        mock_ingests = [MagicMock(), MagicMock()]

        pipeline = Pipeline(mock_ingests, [], [], {})

        assert pipeline.ingest == mock_ingests

    def test_init_stores_transform_sequence(self):
        mock_transforms = [MagicMock()]

        pipeline = Pipeline([], mock_transforms, [], {})

        assert pipeline.transforms == mock_transforms

    def test_init_stores_output_sequence(self):
        mock_outputs = [MagicMock(), MagicMock()]

        pipeline = Pipeline([], [], mock_outputs, {})

        assert pipeline.output == mock_outputs

    def test_init_stores_env_variables(self):
        env_vars = {"KEY": "value", "OTHER": 123}

        pipeline = Pipeline([], [], [], env_vars)

        assert pipeline.variables == env_vars

    def test_init_calls_validate_transform_chain(self):
        with patch.object(Pipeline, "_validate_transform_chain") as mock_validate:
            Pipeline([], [], [], {})

            mock_validate.assert_called_once()


class TestValidateTransformChain:
    def test_validate_empty_transforms_succeeds(self):
        Pipeline([], [], [], {})

    def test_validate_single_transform_succeeds(self):
        mock_transform = MagicMock()
        mock_transform.output_type = DataType.TEXT

        Pipeline([], [mock_transform], [], {})

    def test_validate_compatible_chain_with_list_input_types_succeeds(self):
        transform1 = MagicMock()
        transform1.output_type = DataType.TEXT

        transform2 = MagicMock()
        transform2.supported_input_types = [DataType.TEXT, DataType.JSON]

        Pipeline([], [transform1, transform2], [], {})

    def test_validate_compatible_chain_with_non_list_input_type_succeeds(self):
        transform1 = MagicMock()
        transform1.output_type = DataType.TEXT

        transform2 = MagicMock()
        transform2.supported_input_types = transform1

        Pipeline([], [transform1, transform2], [], {})

    def test_validate_incompatible_chain_raises_type_error(self):
        transform1 = MagicMock()
        transform1.output_type = DataType.PDF
        transform1.__class__.__name__ = "Transform1"

        transform2 = MagicMock()
        transform2.supported_input_types = [DataType.TEXT]
        transform2.__class__.__name__ = "Transform2"

        with pytest.raises(TypeError, match="Transform mismatch"):
            Pipeline([], [transform1, transform2], [], {})

    def test_validate_three_transform_chain_succeeds(self):
        t1 = MagicMock()
        t1.output_type = DataType.XML

        t2 = MagicMock()
        t2.output_type = DataType.JSON
        t2.supported_input_types = [DataType.XML]

        t3 = MagicMock()
        t3.supported_input_types = [DataType.JSON, DataType.TEXT]

        Pipeline([], [t1, t2, t3], [], {})

    def test_validate_fails_at_second_incompatible_pair(self):
        t1 = MagicMock()
        t1.output_type = DataType.TEXT

        t2 = MagicMock()
        t2.output_type = DataType.PDF
        t2.supported_input_types = [DataType.TEXT]
        t2.__class__.__name__ = "Transform2"

        t3 = MagicMock()
        t3.supported_input_types = [DataType.JSON]
        t3.__class__.__name__ = "Transform3"

        with pytest.raises(TypeError, match="Transform2 -> Transform3"):
            Pipeline([], [t1, t2, t3], [], {})


class TestPipelineRun:
    def test_run_calls_all_ingests(self):
        ingest1 = MagicMock()
        ingest1.ingest = AsyncMock(return_value=[])
        ingest2 = MagicMock()
        ingest2.ingest = AsyncMock(return_value=[])

        pipeline = Pipeline([ingest1, ingest2], [], [], {})
        asyncio.run(pipeline.run())

        ingest1.ingest.assert_awaited_once()
        ingest2.ingest.assert_awaited_once()

    def test_run_flattens_ingest_results(self):
        item1 = PipelineItem(name="item1")
        item2 = PipelineItem(name="item2")
        item3 = PipelineItem(name="item3")

        ingest1 = MagicMock()
        ingest1.ingest = AsyncMock(return_value=[item1, item2])
        ingest2 = MagicMock()
        ingest2.ingest = AsyncMock(return_value=[item3])

        output = MagicMock()
        output.export = AsyncMock()

        pipeline = Pipeline([ingest1, ingest2], [], [output], {})
        asyncio.run(pipeline.run())

        assert output.export.await_count == 3

    def test_run_applies_transforms_to_each_item(self):
        item = PipelineItem(name="test")
        ingest = MagicMock()
        ingest.ingest = AsyncMock(return_value=[item])

        transform = MagicMock()
        transform.apply = MagicMock(return_value=[item])

        pipeline = Pipeline([ingest], [transform], [], {})
        asyncio.run(pipeline.run())

        transform.apply.assert_called_once_with(item)

    def test_run_calls_all_outputs_for_each_item(self):
        item = PipelineItem(name="test")
        ingest = MagicMock()
        ingest.ingest = AsyncMock(return_value=[item])

        output1 = MagicMock()
        output1.export = AsyncMock()
        output2 = MagicMock()
        output2.export = AsyncMock()

        pipeline = Pipeline([ingest], [], [output1, output2], {})
        asyncio.run(pipeline.run())

        output1.export.assert_awaited_once_with(item)
        output2.export.assert_awaited_once_with(item)

    def test_run_with_no_items_skips_outputs(self):
        ingest = MagicMock()
        ingest.ingest = AsyncMock(return_value=[])

        output = MagicMock()
        output.export = AsyncMock()

        pipeline = Pipeline([ingest], [], [output], {})
        asyncio.run(pipeline.run())

        output.export.assert_not_awaited()


class TestRunTransforms:
    def test_run_transforms_returns_item_when_no_transforms(self):
        item = PipelineItem(name="test")
        pipeline = Pipeline([], [], [], {})

        result = asyncio.run(pipeline._run_transforms(item))

        assert result == [item]

    def test_run_transforms_applies_single_transform(self):
        input_item = PipelineItem(name="input")
        output_item = PipelineItem(name="output")

        transform = MagicMock()
        transform.apply = MagicMock(return_value=[output_item])

        pipeline = Pipeline([], [transform], [], {})
        result = asyncio.run(pipeline._run_transforms(input_item))

        assert result == [output_item]
        transform.apply.assert_called_once_with(input_item)

    def test_run_transforms_chains_multiple_transforms(self):
        item1 = PipelineItem(name="item1")
        item2 = PipelineItem(name="item2")
        item3 = PipelineItem(name="item3")

        t1 = MagicMock()
        t1.output_type = DataType.TEXT
        t1.apply = MagicMock(return_value=[item2])
        t2 = MagicMock()
        t2.supported_input_types = [DataType.TEXT]
        t2.apply = MagicMock(return_value=[item3])

        pipeline = Pipeline([], [t1, t2], [], {})
        result = asyncio.run(pipeline._run_transforms(item1))

        assert result == [item3]
        t1.apply.assert_called_once_with(item1)
        t2.apply.assert_called_once_with(item2)

    def test_run_transforms_handles_one_to_many_transform(self):
        input_item = PipelineItem(name="input")
        output1 = PipelineItem(name="output1")
        output2 = PipelineItem(name="output2")

        transform = MagicMock()
        transform.apply = MagicMock(return_value=[output1, output2])

        pipeline = Pipeline([], [transform], [], {})
        result = asyncio.run(pipeline._run_transforms(input_item))

        assert result == [output1, output2]

    def test_run_transforms_chains_one_to_many_transforms(self):
        item_a = PipelineItem(name="a")
        item_b1 = PipelineItem(name="b1")
        item_b2 = PipelineItem(name="b2")
        item_c1 = PipelineItem(name="c1")
        item_c2 = PipelineItem(name="c2")

        t1 = MagicMock()
        t1.output_type = DataType.JSON
        t1.apply = MagicMock(return_value=[item_b1, item_b2])
        t2 = MagicMock()
        t2.supported_input_types = [DataType.JSON]
        t2.apply = MagicMock(side_effect=[[item_c1], [item_c2]])

        pipeline = Pipeline([], [t1, t2], [], {})
        result = asyncio.run(pipeline._run_transforms(item_a))

        assert result == [item_c1, item_c2]
        assert t2.apply.call_count == 2


class TestPipelineCreate:
    def test_create_with_empty_config_returns_pipeline(self):
        pipeline = Pipeline.create({}, {})

        assert isinstance(pipeline, Pipeline)
        assert pipeline.ingest == []
        assert pipeline.transforms == []
        assert pipeline.output == []

    def test_create_skips_source_with_missing_repository(self):
        config = {"sources": {"my_source": {"repository": "nonexistent", "objects": []}}}

        with patch("etl.pipeline.base.pipeline_logger") as mock_logger:
            pipeline = Pipeline.create(config, {})

            mock_logger.warning.assert_called_once()
            assert "my_source" in mock_logger.warning.call_args[0][0]
            assert pipeline.ingest == []

    def test_create_skips_destination_with_missing_repository(self):
        config = {"destinations": {"my_output": {"repository": "nonexistent"}}}

        with patch("etl.pipeline.base.pipeline_logger") as mock_logger:
            pipeline = Pipeline.create(config, {})

            mock_logger.warning.assert_called_once()
            assert "my_output" in mock_logger.warning.call_args[0][0]
            assert pipeline.output == []

    def test_create_calls_ingest_factory_with_repository(self):
        mock_repo = MagicMock()
        mock_ingest = MagicMock()

        config = {"sources": {"source1": {"repository": "repo1", "objects": ["obj1"]}}}

        with patch("etl.pipeline.base.Ingest.create", return_value=mock_ingest) as mock_create:
            pipeline = Pipeline.create(config, {"repo1": mock_repo})

            mock_create.assert_called_once_with(mock_repo, objects=["obj1"])
            assert mock_ingest in pipeline.ingest

    def test_create_calls_output_factory_with_repository(self):
        mock_repo = MagicMock()
        mock_output = MagicMock()

        config = {"destinations": {"dest1": {"repository": "repo1", "format": "json"}}}

        with patch("etl.pipeline.base.Output.create", return_value=mock_output) as mock_create:
            pipeline = Pipeline.create(config, {"repo1": mock_repo})

            mock_create.assert_called_once_with(mock_repo, format="json")
            assert mock_output in pipeline.output

    def test_create_calls_transform_factory_for_each_transform(self):
        mock_t1 = MagicMock()
        mock_t1.output_type = DataType.TEXT
        mock_t2 = MagicMock()
        mock_t2.supported_input_types = [DataType.TEXT]

        config = {"transforms": [{"type": "transform1"}, {"type": "transform2"}]}

        with patch("etl.pipeline.base.Transform.create", side_effect=[mock_t1, mock_t2]) as mock_create:
            pipeline = Pipeline.create(config, {})

            assert mock_create.call_count == 2
            assert pipeline.transforms == [mock_t1, mock_t2]

    def test_create_passes_env_variables_as_empty_dict(self):
        pipeline = Pipeline.create({}, {})

        assert pipeline.variables == {}

    def test_create_handles_multiple_sources_and_destinations(self):
        repo1 = MagicMock()
        repo2 = MagicMock()
        mock_ingest = MagicMock()
        mock_output = MagicMock()

        config = {
            "sources": {"src1": {"repository": "r1"}, "src2": {"repository": "r2"}},
            "destinations": {"dst1": {"repository": "r1"}, "dst2": {"repository": "r2"}},
        }

        with patch("etl.pipeline.base.Ingest.create", return_value=mock_ingest):  # noqa: SIM117
            with patch("etl.pipeline.base.Output.create", return_value=mock_output):
                pipeline = Pipeline.create(config, {"r1": repo1, "r2": repo2})

                assert len(pipeline.ingest) == 2
                assert len(pipeline.output) == 2
