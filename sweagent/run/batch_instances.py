import random
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from swerex.deployment.config import (
    DeploymentConfig,
    DockerDeploymentConfig,
    DummyDeploymentConfig,
    LocalDeploymentConfig,
)
from typing_extensions import Self

from sweagent.agent.problem_statement import (
    ProblemStatementConfig,
    TextProblemStatement,
)
from sweagent.environment.repo import (
    GithubRepoConfig,
    LocalRepoConfig,
    PreExistingRepoConfig,
)
from sweagent.environment.swe_env import EnvironmentConfig
from sweagent.utils.files import load_file
from sweagent.utils.log import get_logger

logger = get_logger("swea-config", emoji="🔧")

####################### SEC-BENCH #######################

SECB_IMAGE_PREFIX = "hwiwonlee/secb.eval.x86_64"
# SECB_IMAGE_TAG = "latest"

# Sanitizer error message patterns
SANITIZER_ERROR_PATTERNS = [
    "ERROR: AddressSanitizer:",
    "ERROR: MemorySanitizer:",
    "WARNING: MemorySanitizer:",
    "UndefinedBehaviorSanitizer:DEADLYSIGNAL",
    "ERROR: LeakSanitizer:",
    "SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior",
]

# Sanitizer report patterns
SANITIZER_START_PATTERN = r"==\d+==(?:ERROR|WARNING): (\w+)Sanitizer:"
SANITIZER_END_PATTERN = r"==\d+==ABORTING"
# Stack trace pattern that often appears at the end of sanitizer reports
STACK_TRACE_END_PATTERN = r"\s+#\d+ 0x[0-9a-f]+"


def extract_sanitizer_report(container_output: str) -> str | None:
    """Extract the sanitizer report from container output using regex.

    Args:
        container_output: Container log output

    Returns:
        Extracted sanitizer report or None if no report found
    """
    # Look for complete sanitizer report with both start and end patterns
    start_match = re.search(SANITIZER_START_PATTERN, container_output)
    end_match = re.search(SANITIZER_END_PATTERN, container_output)

    if start_match and end_match:
        # Get the start and end positions of the report
        start_pos = start_match.start()
        end_pos = end_match.end()

        # Make sure end_pos comes after start_pos
        if end_pos > start_pos:
            # Extract the complete report
            return container_output[start_pos:end_pos]

    # If we have a start match but no end match, try to find the last stack trace line
    if start_match and not end_match:
        start_pos = start_match.start()
        # Find all stack trace lines
        stack_trace_matches = list(re.finditer(STACK_TRACE_END_PATTERN, container_output[start_pos:]))
        if stack_trace_matches:
            # Use the last stack trace line as the end point (plus some buffer)
            last_match = stack_trace_matches[-1]
            end_pos = (
                # Find the position after the last stack trace match
                start_pos + last_match.end()
            )
            # Find the next newline after the last stack trace match
            next_newline_pos = container_output.find("\n", end_pos)
            if next_newline_pos != -1:
                end_pos = next_newline_pos + 1  # Include the newline
            end_pos = min(end_pos, len(container_output))
            return container_output[start_pos:end_pos]

    # If we can't find a complete report, check if any sanitizer indicators exist
    if any(indicator in container_output for indicator in SANITIZER_ERROR_PATTERNS):
        # Extract context around the first indicator found
        for indicator in SANITIZER_ERROR_PATTERNS:
            if indicator in container_output:
                idx = container_output.find(indicator)
                # Get up to 1000 characters before and after the indicator
                start_idx = max(0, idx - 1000)
                end_idx = min(len(container_output), idx + 1000)
                return container_output[start_idx:end_idx]

    return None


####################### SEC-BENCH #######################


class AbstractInstanceSource(ABC):
    """Anything that adheres to this standard can be used to load instances."""

    @abstractmethod
    def get_instance_configs(self) -> list[EnvironmentConfig]: ...


class BatchInstance(BaseModel):
    """A single instance in a batch of instances.
    This specifies both the environment configuration and the problem statement.
    """

    env: EnvironmentConfig
    problem_statement: ProblemStatementConfig


def _slice_spec_to_slice(slice_spec: str) -> slice:
    if slice_spec == "":
        return slice(None)
    parts = slice_spec.split(":")
    values = [None if p == "" else int(p) for p in parts]
    if len(parts) == 1:
        return slice(values[0])
    if len(parts) == 2:
        return slice(values[0], values[1])
    if len(parts) == 3:
        return slice(values[0], values[1], values[2])
    msg = (
        f"Invalid slice specification: {slice_spec!r}. "
        "Here's the expected format: stop or start:stop or start:stop:step "
        "(i.e., it behaves exactly like python's list slicing `list[slice]`)."
    )
    raise ValueError(msg)


def _filter_batch_items(
    instances: list[BatchInstance],
    *,
    filter_: str,
    slice_: str = "",
    shuffle: bool = False,
) -> list[BatchInstance]:
    if shuffle:
        instances = sorted(instances.copy(), key=lambda x: x.problem_statement.id)
        random.seed(42)
        random.shuffle(instances)
    before_filter = len(instances)
    instances = [instance for instance in instances if re.match(filter_, instance.problem_statement.id)]
    after_filter = len(instances)
    if before_filter != after_filter:
        logger.info("Instance filter: %d -> %d instances", before_filter, after_filter)
    if slice_:
        instances = instances[_slice_spec_to_slice(slice_)]
        after_slice = len(instances)
        if before_filter != after_slice:
            logger.info("Instance slice: %d -> %d instances", before_filter, after_slice)
    return instances


def _normalize_work_dir(work_dir: str) -> str:
    """Normalize the work_dir path for consistency.

    For paths starting with /src, we ensure we only keep the main project directory
    to be used as the repo_name.
    """
    if work_dir.startswith("/src"):
        parts = work_dir.split("/")
        if len(parts) > 2 and parts[2]:
            return "/src/" + parts[2]
    return work_dir


class SimpleBatchInstance(BaseModel):
    """A simple way to configure a single instance in a batch of instances that all
    use similar deployment configurations.

    Predominantly used for benchmarking purposes. Assumes that the repository is already
    present in the docker container.
    """

    image_name: str
    problem_statement: str
    id: str
    repo_name: str = ""
    """Specifies the repository to use. If empty, no repository is used.
    If the string does not contain a slash, it is interpreted as an already existing repository at the root
    of the docker container. If it contains the word "github", it is interpreted as a github repository.
    Else, it is interpreted as a local repository.
    """
    base_commit: str = "HEAD"
    """Used to reset repo."""
    extra_fields: dict[str, Any] = Field(default_factory=dict)
    """Any additional data to be added to the instance.
    This data will be available when formatting prompt templates.
    """

    def to_full_batch_instance(self, deployment: DeploymentConfig) -> BatchInstance:
        """Merge the deployment options into the `SimpleBatchInstance` object to get a full `BatchInstance`."""
        # Very important: Make a copy of the deployment config because it will be shared among instances!!!
        deployment = deployment.model_copy(deep=True)
        problem_statement = TextProblemStatement(
            text=self.problem_statement, id=self.id, extra_fields=self.extra_fields
        )
        if not self.repo_name:
            repo = None
        elif "github" in self.repo_name:
            repo = GithubRepoConfig(github_url=self.repo_name, base_commit=self.base_commit)
        elif self.repo_name.startswith("/src/"):
            # For paths starting with /src/, create a PreExistingRepoConfig with the full path
            # This preserves the entire path including /src/ prefix
            repo = PreExistingRepoConfig(repo_name=self.repo_name, base_commit=self.base_commit)
        elif "/" not in self.repo_name:
            repo = PreExistingRepoConfig(repo_name=self.repo_name, base_commit=self.base_commit)
        else:
            repo = LocalRepoConfig(path=Path(self.repo_name), base_commit=self.base_commit)
        if isinstance(deployment, LocalDeploymentConfig):
            if self.image_name:
                msg = "Local deployment does not support image_name"
                raise ValueError(msg)
            return BatchInstance(
                env=EnvironmentConfig(deployment=deployment, repo=repo),
                problem_statement=problem_statement,
            )
        if isinstance(deployment, DummyDeploymentConfig):
            return BatchInstance(
                env=EnvironmentConfig(deployment=deployment, repo=repo),
                problem_statement=problem_statement,
            )
        deployment.image = self.image_name  # type: ignore
        deployment.python_standalone_dir = None if self.image_name.startswith(SECB_IMAGE_PREFIX) else "/root"  # type: ignore
        deployment.docker_args = (  # type: ignore
            ["--security-opt", "seccomp=unconfined"] if self.image_name.startswith(SECB_IMAGE_PREFIX) else []
        )
        return BatchInstance(
            env=EnvironmentConfig(deployment=deployment, repo=repo),
            problem_statement=problem_statement,
        )

    @classmethod
    def from_swe_bench(cls, instance: dict[str, Any]) -> Self:
        """Convert instances from the classical SWE-bench dataset to the `SimpleBatchInstance` format."""
        iid = instance["instance_id"]
        image_name = instance.get("image_name", None)
        if image_name is None:
            # Docker doesn't allow double underscore, so we replace them with a magic token
            id_docker_compatible = iid.replace("__", "_1776_")
            image_name = f"swebench/sweb.eval.x86_64.{id_docker_compatible}:v1"
        return cls(
            image_name=image_name,
            problem_statement=instance["problem_statement"],
            id=iid,
            repo_name="testbed",
            base_commit=instance["base_commit"],
        )

    @classmethod
    def from_sec_bench(cls, instance: dict[str, Any], type: Literal["secb_patch", "secb_poc"] = "secb_patch") -> Self:
        """Convert instances from the secbench dataset to the `SimpleBatchInstance` format."""
        iid = instance["instance_id"]
        # Get work_dir from instance
        work_dir = _normalize_work_dir(instance["work_dir"])
        if type == "secb_patch":
            image_name = f"{SECB_IMAGE_PREFIX}.{iid}:patch"
            bug_description = instance["bug_report"]
        elif type == "secb_poc":
            image_name = f"{SECB_IMAGE_PREFIX}.{iid}:poc"
            bug_description = instance["sanitizer_report"]

        # problem_statement = f"\n--------REPORT START--------\n{bug_description}\n--------REPORT END--------\n\n<uploaded_files>\n{work_dir}\n</uploaded_files>\n\nI've uploaded a code repository in the directory `{work_dir}`. Your task is to make the minimal changes to non-tests files in the `{work_dir}` repository directory to ensure the crash points specified in the sanitizer report are not triggered."
        problem_statement = f"<uploaded_files>\n{work_dir}\n</uploaded_files>\nI've uploaded a code repository in the directory `{work_dir}`. Consider the following issue description:\n\n<issue_description>\n{bug_description}\n</issue_description>\n\n"

        return cls(
            image_name=image_name,
            problem_statement=problem_statement,
            id=iid,
            repo_name=work_dir,
            base_commit=instance["base_commit"],
        )


class InstancesFromFile(BaseModel, AbstractInstanceSource):
    """Load instances from a file."""

    path: Path
    filter: str = ".*"
    """Regular expression to filter the instances by instance id."""
    slice: str = ""
    """Select only a slice of the instances (after filtering by `filter`).
    Possible values are stop or start:stop or start:stop:step
    (i.e., it behaves exactly like python's list slicing `list[slice]`).
    """
    shuffle: bool = False
    """Shuffle the instances (before filtering and slicing)."""

    deployment: DeploymentConfig = Field(
        default_factory=lambda: DockerDeploymentConfig(image="python:3.11"),
        description="Deployment options.",
    )
    """Note that the image_name option is overwritten by the images specified in the task instances."""

    simple: Literal[True] = True
    """Convenience discriminator for (de)serialization/CLI. Do not change."""

    type: Literal["file"] = "file"
    """Discriminator for (de)serialization/CLI. Do not change."""

    def get_instance_configs(self) -> list[BatchInstance]:
        instance_dicts = load_file(self.path)
        simple_instances = [SimpleBatchInstance.model_validate(instance_dict) for instance_dict in instance_dicts]
        instances = [instance.to_full_batch_instance(self.deployment) for instance in simple_instances]
        return _filter_batch_items(instances, filter_=self.filter, slice_=self.slice, shuffle=self.shuffle)

    @property
    def id(self) -> str:
        return self.path.stem


class InstancesFromHuggingFace(BaseModel, AbstractInstanceSource):
    """Load instances from HuggingFace."""

    dataset_name: str
    """Name of the HuggingFace dataset. Same as when using `datasets.load_dataset`."""
    split: str = "dev"
    filter: str = ".*"
    """Regular expression to filter the instances by instance id."""
    slice: str = ""
    """Select only a slice of the instances (after filtering by `filter`).
    Possible values are stop or start:stop or start:stop:step.
    (i.e., it behaves exactly like python's list slicing `list[slice]`).
    """
    shuffle: bool = False
    """Shuffle the instances (before filtering and slicing)."""

    deployment: DeploymentConfig = Field(
        default_factory=lambda: DockerDeploymentConfig(image="python:3.11"),
    )
    """Deployment configuration. Note that the `image_name` option is overwritten by the images specified in the task instances.
    """
    type: Literal["huggingface"] = "huggingface"
    """Discriminator for (de)serialization/CLI. Do not change."""

    def get_instance_configs(self) -> list[BatchInstance]:
        from datasets import load_dataset

        ds: list[dict[str, Any]] = load_dataset(self.dataset_name, split=self.split)  # type: ignore
        simple_instances: list[SimpleBatchInstance] = [SimpleBatchInstance.model_validate(instance) for instance in ds]
        instances = [instance.to_full_batch_instance(self.deployment) for instance in simple_instances]
        return _filter_batch_items(instances, filter_=self.filter, slice_=self.slice, shuffle=self.shuffle)

    @property
    def id(self) -> str:
        ds_name = "".join(l for l in self.dataset_name if l.isalnum() or l in ["-", "_"])
        return f"{ds_name}_{self.split}"


class SWEBenchInstances(BaseModel, AbstractInstanceSource):
    """Load instances from SWE-bench."""

    subset: Literal["lite", "verified", "full"] = "lite"

    split: Literal["dev", "test"] = "dev"

    deployment: DeploymentConfig = Field(
        default_factory=lambda: DockerDeploymentConfig(image="python:3.11"),
    )
    """Deployment configuration. Note that the image_name option is overwritten by the images specified in the task instances.
    """

    type: Literal["swe_bench"] = "swe_bench"
    """Discriminator for (de)serialization/CLI. Do not change."""

    filter: str = ".*"
    """Regular expression to filter the instances by instance id."""
    slice: str = ""
    """Select only a slice of the instances (after filtering by `filter`).
    Possible values are stop or start:stop or start:stop:step.
    (i.e., it behaves exactly like python's list slicing `list[slice]`).
    """
    shuffle: bool = False
    """Shuffle the instances (before filtering and slicing)."""

    evaluate: bool = False
    """Run sb-cli to evaluate"""

    def _get_huggingface_name(self) -> str:
        if self.subset == "full":
            return "princeton-nlp/SWE-Bench"
        elif self.subset == "verified":
            return "princeton-nlp/SWE-Bench_Verified"
        elif self.subset == "lite":
            return "princeton-nlp/SWE-Bench_Lite"
        msg = f"Unsupported subset: {self.subset}"
        raise ValueError(msg)

    def get_instance_configs(self) -> list[BatchInstance]:
        from datasets import load_dataset

        ds: list[dict[str, Any]] = load_dataset(self._get_huggingface_name(), split=self.split)  # type: ignore
        self.deployment.platform = "linux/amd64"
        instances = [
            SimpleBatchInstance.from_swe_bench(instance).to_full_batch_instance(self.deployment) for instance in ds
        ]
        return _filter_batch_items(instances, filter_=self.filter, slice_=self.slice, shuffle=self.shuffle)

    @property
    def id(self) -> str:
        return f"swe_bench_{self.subset}_{self.split}"


class ExpertInstancesFromFile(BaseModel, AbstractInstanceSource):
    """Load instances from a file. The difference to `InstancesFromFile` is that the instances are configured as full
    `EnvironmentInstanceConfig` objects, i.e., we could specify separate deployment configurations etc.
    """

    path: Path
    filter: str = ".*"
    """Regular expression to filter the instances by instance id."""
    slice: str = ""
    """Select only a slice of the instances (after filtering by `filter`).
    Possible values are stop or start:stop or start:stop:step.
    (i.e., it behaves exactly like python's list slicing `list[slice]`).
    """
    shuffle: bool = False
    """Shuffle the instances (before filtering and slicing)."""

    type: Literal["expert_file"] = "expert_file"
    """Discriminator for (de)serialization/CLI. Do not change."""

    def get_instance_configs(self) -> list[BatchInstance]:
        instance_dicts = load_file(self.path)
        instances = [BatchInstance.model_validate(instance_dict) for instance_dict in instance_dicts]
        return _filter_batch_items(instances, filter_=self.filter, slice_=self.slice, shuffle=self.shuffle)

    @property
    def id(self) -> str:
        return self.path.stem


class SecBenchPatchInstances(BaseModel, AbstractInstanceSource):
    """Load instances from SecBench."""

    dataset_name: str
    """Name of the HuggingFace dataset. Same as when using `datasets.load_dataset`."""
    split: str = "test"
    filter: str = ".*"
    """Regular expression to filter the instances by instance id."""
    slice: str = ""
    """Select only a slice of the instances (after filtering by `filter`).
    Possible values are stop or start:stop or start:stop:step.
    (i.e., it behaves exactly like python's list slicing `list[slice]`).
    """
    shuffle: bool = False
    """Shuffle the instances (before filtering and slicing)."""

    type: Literal["secb_patch"] = "secb_patch"
    """Discriminator for (de)serialization/CLI. Do not change."""

    deployment: DeploymentConfig = Field(
        default_factory=lambda: DockerDeploymentConfig(image="python:3.11"),
    )

    def get_instance_configs(self) -> list[BatchInstance]:
        from datasets import load_dataset

        ds: list[dict[str, Any]] = load_dataset(self.dataset_name, split=self.split)  # type: ignore
        instances = []
        for instance in ds:
            try:
                si = SimpleBatchInstance.from_sec_bench(instance, type="secb_patch")
                instances.append(si.to_full_batch_instance(self.deployment))
            except ValueError as e:
                logger.error(
                    "Skipping instance %s due to docker build failure: %s",
                    instance.get("instance_id"),
                    e,
                )
        return _filter_batch_items(instances, filter_=self.filter, slice_=self.slice, shuffle=self.shuffle)

    @property
    def id(self) -> str:
        return f"secb_patch_{self.split}"


class SecBenchPocInstances(BaseModel, AbstractInstanceSource):
    """Load instances from SecBench."""

    dataset_name: str
    """Name of the HuggingFace dataset. Same as when using `datasets.load_dataset`."""
    split: str = "test"
    filter: str = ".*"
    """Regular expression to filter the instances by instance id."""
    slice: str = ""
    """Select only a slice of the instances (after filtering by `filter`).
    Possible values are stop or start:stop or start:stop:step.
    (i.e., it behaves exactly like python's list slicing `list[slice]`).
    """
    shuffle: bool = False
    """Shuffle the instances (before filtering and slicing)."""

    type: Literal["secb_poc"] = "secb_poc"
    """Discriminator for (de)serialization/CLI. Do not change."""

    deployment: DeploymentConfig = Field(
        default_factory=lambda: DockerDeploymentConfig(image="python:3.11"),
    )

    def get_instance_configs(self) -> list[BatchInstance]:
        from datasets import load_dataset

        ds: list[dict[str, Any]] = load_dataset(self.dataset_name, split=self.split)  # type: ignore
        instances = []
        for instance in ds:
            try:
                si = SimpleBatchInstance.from_sec_bench(instance, type="secb_poc")
                instances.append(si.to_full_batch_instance(self.deployment))
            except ValueError as e:
                logger.error(
                    "Skipping instance %s due to docker build failure: %s",
                    instance.get("instance_id"),
                    e,
                )
        return _filter_batch_items(instances, filter_=self.filter, slice_=self.slice, shuffle=self.shuffle)

    @property
    def id(self) -> str:
        return f"secb_poc_{self.split}"


BatchInstanceSourceConfig = (
    InstancesFromHuggingFace
    | InstancesFromFile
    | SWEBenchInstances
    | ExpertInstancesFromFile
    | SecBenchPatchInstances
    | SecBenchPocInstances
)
