请你为我讲解swe-agent中是如何创建实例docker的？具体的，一步一步的，具体的说明在任务的哪一个阶段构建的docker？如何构建的docker(例如利用base image, 如何动态调整等等)，给我详细的流程与步骤

SWE-agent中Docker实例创建的详细流程

  根据我对SWE-agent代码的深入分析，我现在为您详细讲解Docker实例是如何创建的：

  1. 任务执行的入口点和时机

  Docker实例创建在以下几个关键阶段进行：

  1.1 单任务执行 (sweagent run)

  - 入口: sweagent/run/run_single.py - RunSingle 类
  - 时机: 当用户通过CLI执行 sweagent run 命令时
  - 触发点: env.start() 方法调用时

  1.2 批量任务执行 (sweagent run-batch)

  - 入口: sweagent/run/run_batch.py - RunBatch 类
  - 时机: 处理每个批量实例时
  - 触发点: 对每个 BatchInstance 调用 env.start() 时

  2. 配置系统和部署策略

  2.1 环境配置结构

  # sweagent/environment/swe_env.py:32
  class EnvironmentConfig(BaseModel):
      deployment: DeploymentConfig = Field(
          default_factory=lambda: DockerDeploymentConfig(
              image="python:3.11",
              python_standalone_dir="/root"
          ),
          description="Deployment options."
      )

  2.2 默认Docker配置

  - 默认基础镜像: python:3.11
  - 平台架构: linux/amd64 (SWE-Bench实例中强制设定)
  - 工作目录: /root

  3. Docker镜像构建和动态配置过程

  3.1 SWE-Bench特殊镜像机制

  SWE-agent对SWE-Bench数据集有特殊的Docker镜像处理：

  # sweagent/run/batch_instances.py:258
  image_name = f"swebench/sweb.eval.x86_64.{id_docker_compatible}:v1"

  SWE-Bench镜像命名规则:
  - 格式: swebench/sweb.eval.x86_64.<instance_id>:v1
  - 双下划线处理: __ 替换为 _1776_
  - 示例: swebench/sweb.eval.x86_64.pydicom_1776_pydicom-1458:v1

  3.2 SEC-Bench镜像机制

  对于安全基准测试，使用不同的镜像前缀：

  # sweagent/run/batch_instances.py:33
  SECB_IMAGE_PREFIX = "hwiwonlee/secb.eval.x86_64"
  # 格式: hwiwonlee/secb.eval.x86_64.<instance_id>:patch 或 :poc

  4. 完整的Docker实例创建流程

  步骤1: 配置解析和验证

  1. 从YAML配置文件解析 EnvironmentConfig
  2. 创建 DeploymentConfig (通常是 DockerDeploymentConfig)
  3. 设置默认镜像和参数

  步骤2: 批量实例处理

  对于SWE-Bench等批量数据：
  # sweagent/run/batch_instances.py:410-413
  instances = [
      SimpleBatchInstance.from_swe_bench(instance).to_full_batch_instance(self.deployment)
      for instance in ds
  ]

  动态镜像名覆盖:
  # sweagent/run/batch_instances.py:321
  def to_full_batch_instance(self, deployment: DeploymentConfig) -> BatchInstance:
      deployment = deployment.model_copy(deep=True)
      deployment.image = self.image_name  # 覆盖默认镜像

  步骤3: SWE-ReX部署系统启动

  # sweagent/environment/swe_env.py:113-118
  def start(self) -> None:
      self._init_deployment()
      self.reset()
      for command in self._post_startup_commands:
          self.communicate(command, timeout=self.post_startup_command_timeout)

  步骤4: Docker容器初始化

  # sweagent/environment/swe_env.py:189-200
  def _init_deployment(self) -> None:
      self._chook.on_start_deployment()
      asyncio.run(self.deployment.start())  # SWE-ReX启动容器
      asyncio.run(self.deployment.runtime.create_session(
          CreateBashSessionRequest(startup_source=["/root/.bashrc"])
      ))
      self.set_env_variables({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})

  步骤5: 代码库复制和环境重置

  # sweagent/environment/swe_env.py:139-155
  def reset(self):
      self.communicate(input="cd /", check="raise")
      if not ("osv-" in self.name or "cve-" in self.name):
          self._copy_repo()
          self._reset_repository()
      self._chook.on_environment_startup()

  步骤6: 代码库状态重置

  # sweagent/environment/swe_env.py:165-179
  startup_commands = [
      f"cd /{self.repo.repo_name}",
      "export ROOT=$(pwd -P)",
      "git status",
      "git restore .",
      f"git reset --hard {self.repo.base_commit}",
      "git clean -fdq",
  ]

  5. 关键的动态配置特性

  5.1 镜像名动态覆盖

  - 每个SWE-Bench实例都有预构建的专用镜像
  - 镜像包含特定版本的依赖和环境设置
  - 运行时自动覆盖默认的 python:3.11 镜像

  5.2 环境变量提取

  在批量运行中，SWE-agent会从Docker镜像中提取原始环境变量：
  # sweagent/run/run_batch.py:约330行
  client = docker.from_env()
  image = client.images.get(instance.env.deployment.image)
  env_attrs = image.attrs.get("Config", {}).get("Env", [])
  original_env = dict(item.split("=", 1) for item in env_attrs if "=" in item)
  env.set_env_variables(original_env)

  5.3 平台架构强制设定

  对于SWE-Bench实例：
  # sweagent/run/batch_instances.py:410
  self.deployment.platform = "linux/amd64"

  6. 工具系统集成

  在容器启动后，SWE-agent会上传工具包：
  # sweagent/tools/tools.py
  await env.deployment.runtime.upload(
      UploadRequest(
          source_path=bundle.path.as_posix(),
          target_path=f"/root/tools/{bundle.path.name}",
      )
  )

  总结

  SWE-agent的Docker实例创建是一个高度自动化和动态的过程：

  1. 预构建镜像: SWE-Bench等基准测试使用预构建的专用镜像
  2. 动态配置: 运行时根据任务类型动态选择和配置容器
  3. 环境隔离: 每个任务在独立的Docker容器中执行
  4. 状态管理: 自动处理代码库克隆、状态重置和环境准备
  5. 工具集成: 自动上传和配置所需的工具包

  整个过程通过SWE-ReX库进行底层的容器管理，SWE-agent在上层提供了高级的配置和任务管理接口。