# **优化自主代理以实现精确概念验证（PoC）生成的战略研究计划**

## **执行摘要**

本报告旨在为优化一个基线概念验证（PoC）生成代理提供一份战略研究计划。当前任务的核心挑战在于，将一个通用软件工程代理（如SWE-Agent）转变为一个能够精确复现由代码消毒剂（Sanitizer）报告的特定错误的专用工具。这一目标要求代理不仅能修复宽泛的漏洞，更需具备生成能触发特定、精确运行时错误状态的PoC的能力，这是一个对精度要求极高的任务。

为应对此挑战，本计划提出一个分层、协同的优化策略，该策略建立在三大核心支柱之上：

1. **强化感知与行动能力**：通过重构代理与计算机的交互接口（ACI），为其装备调试器（如GDB）和结构化错误解析器等专业工具，使其能够像安全研究员一样感知和操作其执行环境。  
2. **引入先进推理框架**：在代理的核心循环中集成轻量级的自我修正与规划机制。通过融合“反思”（Reflexion）框架与结构化假设管理，使代理从简单的试错模式演进为具备审慎规划和深度事后分析能力的智能体。  
3. **聚焦上下文精度**：利用静态程序分析技术（如污点分析和程序切片）作为预处理步骤，在代理开始工作前，从庞大的代码库中提取出与漏洞最相关的最小代码子集。这极大地降低了代理的认知负荷，提升了其在复杂项目中的效率和成功率。

最终，本报告提出一个循序渐进的实施路线图。该路线图建议首先从集成动态分析工具和构建高保真反馈循环入手，这是后续所有高级功能的基础。在此之上，引入自我修正的认知循环。最后，通过集成静态分析技术来优化效率和扩展性。这一分阶段的方法确保了研发工作的重点突出、风险可控，并能以最高效的方式实现从通用代理到专业化PoC生成工具的转变。

---

## **第一节：基础能力增强：优化代理的感知与行动循环**

一个自主代理的效能，其根本上限取决于它感知环境并对其采取行动的能力。对于精确PoC生成的任务而言，SWE-Agent的默认工具集是基础性的，但远非足够。为了达成目标，必须为代理装备安全研究员的“感官”和“肢体”，即专业的动态分析和调试工具。本节将聚焦于对代理核心交互循环进行高杠杆、基础性的改进。

### **1.1 演进面向漏洞分析的代理-计算机接口（ACI）**

#### **当前状态分析**

基线SWE-Agent的ACI为通用软件工程任务提供了一套简洁而有效的动作集，主要包括查看、搜索和编辑文件 1。其优势在于设计简单，易于语言模型理解和使用 1。然而，该接口完全缺乏动态分析或调试工具，而这些工具对于漏洞复现是不可或缺的。其架构依赖于一个在Docker容器内运行的shell会话，由SWE-ReX包进行管理 2，这为后续扩展提供了一个坚实的基础。

#### **ACI增强提案：将调试器作为一等工具**

我们提议将调试器（具体为GDB）作为一等工具集成到ACI中。这不仅仅是在GDB下运行程序，而是要创建一个代理可以完全控制的、交互式的、有状态的调试会话。

* **工具规格定义**：定义新的ACI命令，例如gdb\_start(program\_args)、gdb\_run()、gdb\_set\_breakpoint(file:line)、gdb\_print(variable)和gdb\_backtrace()。这种设计遵循了动作应简单、紧凑且高效的原则 1，将一个功能复杂的调试器分解为一系列离散、易于语言模型理解的原子操作。  
* **技术实现**：这需要在代理的环境管理器（SWEEnv/SWE-ReX）中进行修改，使其能够为主shell之外的GDB维护一个持久化的PTY（伪终端）会话。ChatDBG 4 和用于GDB的MCP服务器 5 等现有框架为此提供了可借鉴的架构模式，它们展示了如何赋予LLM自主控制权以导航堆栈和检查程序状态。

#### **ACI增强提案：消毒剂输出解析器**

代理需要精确理解它试图复现的错误。原始的、非结构化的消毒剂日志对于LLM来说信息密度低且难以解析。

* **工具规格定义**：创建一个新的ACI命令run\_with\_sanitizer(program\_args)，该命令负责执行目标程序并捕获标准错误输出。其核心创新在于一个结构化解析器，它能将AddressSanitizer（ASan）或UndefinedBehaviorSanitizer（UBSan）的原始文本输出转换为一个JSON对象。该对象应包含error\_type、file、line\_number、function、stack\_trace和memory\_address等字段。  
* **理论依据**：相比于原始文本，这种结构化数据对LLM的效用要大得多。它能够直接输入到后续的反馈和推理循环中（见后文），使代理能够精确地比较其生成的崩溃与目标崩溃之间的差异，从而进行有针对性的调整。

### **1.2 集成动态分析以构建高保真反馈循环**

#### **“执行盲点”问题**

标准的代理循环常常存在一个“执行可见性”的盲点；LLM生成了代码，却无法“看到”代码实际运行后发生了什么 6。我们的目标是通过将丰富的运行时遥测数据反馈给代理来闭合这个反馈循环。

#### **从二元反馈到富信息反馈**

当前许多代理的反馈机制仅限于测试用例的通过/失败状态。对于PoC生成任务，这种二元信息是严重不足的。代理需要理解一次“失败”的性质和质量。

* **实现方式**：run\_with\_sanitizer工具是此反馈循环的核心。在每次PoC尝试之后，代理将调用此工具。环境返回的不再是简单的“通过”或“失败”，而是由消毒剂解析器生成的结构化JSON输出。  
* **反馈循环机制**：代理的核心循环将被修改，以将这个结构化的反馈附加到其历史记录中。下一个回合的提示将明确指示代理比较actual\_crash\_details（来自其上一次运行）和target\_crash\_details（来自初始报告），并根据两者之间的差异来制定下一步行动。这个过程模拟了人类开发者的调试实践 7，使代理的每一步行动都基于具体的、可操作的数据。

#### **从无状态执行到有状态交互的架构演进**

mini-swe-agent因其极致的简洁性而备受赞誉，它通过独立的subprocess.run调用来执行每个命令 8。这种无状态的执行模型对于通用任务的稳定性和可扩展性非常有利。然而，漏洞分析，尤其是调试，本质上是一个有状态的、交互式的过程。对GDB进行交互式控制的需求 4 与无状态执行模型是直接冲突的。

要实现精确的错误复现，通常需要通过调试来理解程序在失败瞬间的状态。像GDB这样的调试工具是交互式的；它们在多个命令之间维持着状态（例如断点、当前堆栈帧等）。最简单的代理执行模型，如mini-swe-agent的无状态模型，无法支持交互式GDB会话。因此，一个更复杂的、有状态的执行后端，如SWE-agent 1.0所使用的SWE-ReX 2，不仅是一个有用的特性，而是一个硬性要求。

这意味着，对于当前任务，必须刻意地从“极致简洁”的无状态模型转向拥抱状态化会话管理的复杂性。首要且最关键的工程任务是确保SWE-ReX环境能够可靠地管理一个与主shell并存的、长生命周期的交互式GDB会话。这是实现任何有意义进展的基础性先决条件，也代表了对通用SWE-Agent设置的第一个重大、专门化的改造。

---

## **第二节：先进推理与自我修正框架**

在建立了一个强大的感知-行动循环之后，下一个前沿是提升代理的“认知”能力。我们需要将代理从简单的试错模式，转变为一种更深思熟虑、更具战略性的问题解决方法。这是在庞大的、可能触发漏洞的输入空间中进行高效导航的最有效途径。

### **2.1 实现轻量级的“反思”（Reflexion）循环以进行迭代优化**

#### **核心概念**

Reflexion框架通过语言反馈而非更新模型权重来强化代理 9。代理对其失败进行口头反思，将这些反思文本存储在记忆中，并用它们来指导未来的尝试。这是一种引入“系统2”思维模式的轻量级而强大的方法 12。

#### **针对PoC生成的架构设计**

* **行动者（Actor）**：基线的SWE-Agent，负责生成PoC文件和运行它的命令。  
* **评估者（Evaluator）**：这并非一个独立的LLM调用，而是我们在1.2节中设计的动态分析工具链。所谓的“评估”就是消毒剂输出的结构化数据，以及它与目标崩溃的比较结果。  
* **自我反思（Self-Reflection）**：这是关键的新增步骤。在一次失败的尝试之后，引入一个新的步骤，向LLM提供包含其行动轨迹、消毒剂输出的提示，并附上一个特定的指令：“你是一名安全研究员。你上一次触发漏洞的尝试导致了\[实际崩溃详情\]，但目标是\[目标崩溃详情\]。请分析其中的差异。撰写一段简短的自我反思，解释为什么你的尝试失败了，并为下一次尝试提出一个具体的、可操作的策略。”

#### **记忆整合**

生成的自我反思文本将被前置到下一个“行动者”步骤的上下文中。这种设计明确地指导代理，防止其陷入重复的失败循环 12。例如，一段反思可能是：“我之前的输入在第50行的strcpy中引发了崩溃，但目标崩溃是第72行的堆溢出。这表明输入流向了错误的代码路径。我的下一次尝试应该专注于构造一个能执行到第65行内存分配路径的输入。”

### **2.2 结构化假设生成与管理（一种“轻量级思维树”方法）**

#### **反应式代理的问题**

一个纯粹的反应式代理（如ReAct）可能会在一长串的行动中迷失方向。对于复杂问题，需要一种更结构化的方式来探索解决方案空间。思维树（Tree of Thoughts, ToT）为同时探索多个推理路径提供了一个框架 13。然而，一个完整的ToT实现可能相当复杂。

#### **轻量级替代方案：假设驱动的探索**

我们提出一个更简单的、串行的、受ToT和科学发现模型启发的アプローチ 16。代理将一次只生成和测试一个明确的假设，而不是探索一整棵树。

* **步骤1（假设）**：在每次尝试开始时，提示代理：“根据消毒剂报告和源代码，为漏洞的根本原因提出一个单一的、可测试的假设。例如：‘该漏洞是parse\_input函数中的堆缓冲区溢出，当输入字符串超过1024字节并包含特定头部时触发。’”  
* **步骤2（规划与执行）**：然后，代理生成一个简短的计划，使用专门的ACI工具来测试这个假设。例如：“1. 创建一个包含1025字节输入字符串的PoC文件。2. 在parse\_input的开头设置一个断点。3. 使用调试器运行并检查缓冲区分配的大小。”  
* **步骤3（验证与反思）**：代理执行该计划。结果（调试器状态、消毒剂输出）要么证实要么证伪该假设。这个结果直接输入到2.1节的Reflexion循环中，为下一个假设提供信息。这创造了一个结构化的、自我纠正的推理过程，比无方向的探索更有效率。

#### **融合反思与假设管理，构建安全领域的认知循环**

Reflexion框架 9 提供了一种对失败进行*事后*分析的机制。而假设驱动的框架 16 和ToT 15 则提供了一种进行*事前*规划和探索的机制。它们通常被视为独立的代理架构。然而，对于漏洞分析这一特定任务，这两个概念是同一枚硬币的两面。

安全研究员的工作流程恰好就是这样一个循环：对一个漏洞形成一个假设，设计一个测试，观察结果，然后*反思*这个结果以形成一个*新的、更好的*假设。一个人类专家可以无缝地完成这两件事：一次失败的测试（反思）直接为下一个假设提供了信息。

因此，最有力的推理能力升级不是单独实现其中之一，而是将它们融合成一个单一的、连贯的认知循环。Reflexion框架中“反思”步骤的输出，成为下一次迭代中“假设”步骤的直接输入。这就创建了一个紧密而高效的循环：**假设 \-\> 规划 \-\> 执行 \-\> 观察 \-\> 反思 \-\> 假设...**。与通用的规划者/审查者多代理系统 18 或一个完整的ToT搜索相比，这种架构更具领域特异性，并且对于解决当前问题可能更有效。通过将“反思提示”的输出与“假设提示”的输入明确地联系起来，我们可以构建一个更接近专家工作流程的、基于LLM的推理过程，从而更快地收敛到解决方案。

---

## **第三节：战略性代码分析以实现上下文精度**

LLM的性能对其上下文窗口的质量和大小高度敏感 19。在每一步都向代理提供整个代码库是低效、昂贵且常常适得其反的。解锁高性能和高效率的关键在于，大幅减少代理需要考虑的代码量，将其注意力仅集中在与漏洞相关的部分。在这一方面，自动化程序分析技术成为不可或缺的预处理工具。

### **3.1 利用污点分析追踪易受攻击的数据流**

#### **概念**

污点分析是一种静态分析形式，它追踪数据从不受信任的来源（“源”）到程序中敏感位置（“汇”）的流动 20。对于PoC生成任务，这一技术极其强大：它能显示攻击者控制的输入到达memcpy或system等易受攻击函数所经过的确切路径。

#### **集成策略**

在代理开始工作之前，一个静态分析工具，如CodeQL 20 或Joern 21，将对代码库运行。

* **识别源与汇**：消毒剂报告通常会告诉我们“汇”（即崩溃的函数）。“源”通常是用户控制的输入，如函数参数或从文件中读取的数据。  
* **生成污点路径**：查询工具以找到从源到汇的所有代码路径。  
* **作为上下文提供**：得到的污点路径——一个包含函数和代码行的列表——将作为初始上下文的一部分提供给代理。提示将是：“这是消毒剂报告。静态污点分析已识别出从输入到崩溃位置的以下路径：\[污点路径\]。请使用此信息指导你的PoC生成。” 这能立即将代理的努力集中在相关的控制流上。

### **3.2 使用程序切片创建最小化代码上下文**

#### **概念**

程序切片是一种技术，用于提取影响特定变量或语句（“切片标准”）的一个最小的、可执行的程序子集 22。这极大地减少了开发者——或代理——需要检查的代码量 21。

#### **集成策略**

* **切片标准**：切片标准将是消毒剂报告中确定的确切代码行。  
* **生成切片**：使用3.1节中的污点路径来指导过程间分析，程序切片器将生成一个“漏洞切片”。该切片仅包含从源头开始，沿着污点路径，直到汇点的代码行。  
* **聚焦式提示**：代理的主要代码上下文将是这个切片，而不是整个文件。提示变为：“你的任务是触发在X行的错误。以下代码切片包含了与此漏洞相关的所有代码：\[代码切片\]”。

#### **收益**

这种方法有多种好处：它极大地减少了发送给LLM的令牌数量，从而降低了成本和延迟；它通过移除分散注意力的、不相关的代码来提高LLM的推理质量 21；它从根本上简化了代理的任务，从而提高了成功的概率。近期的研究表明，由LLM驱动的代理甚至可以自己执行切片（如SliceMate 23），但对于一个PoC项目，集成现有工具是更高效的选择。

#### **静态分析作为“认知卸载器”和“提示压缩引擎”**

静态分析工具 20 和代理推理框架 9 在研究中通常被视为独立的解决方案。代理通常被赋予*运行*分析工具的能力。然而，运行静态分析的计算成本高且过程复杂，这并不适合代理的迭代式、试错循环。让一个LLM去尝试构建正确的CodeQL查询，是对其能力的一种低效利用。

相比之下，这些工具的*输出*则非常适合作为LLM的输入。因此，最有效的架构不是让代理成为静态分析工具的使用者，而是将静态分析用作一个自动化的、一次性的*预处理步骤*。它通过预先执行复杂的依赖和数据流分析，扮演了“认知卸载器”的角色。其输出（切片和污点路径）则充当了一个高效的“提示压缩引擎”。这不仅是减少了令牌数量，更是提高了提示的*信息密度*，为代理提供了预先消化好的洞见。

这种设计从根本上改变了代理任务的性质，从“代码库理解和漏洞搜寻”转变为“在已知的、受限的上下文中进行有针对性的利用生成”。LLM代理受限于上下文长度，并且在处理不相关信息时表现不佳 19。而漏洞往往依赖于大型代码库中复杂的交互。静态分析工具正是为发现这些复杂交互而设计的，但它们运行缓慢且操作复杂。如果让代理迭代地运行这些工具，将会非常缓慢且容易出错。然而，一次性的、预先的分析可以识别出关键的代码上下文（即切片）。将这个小而高度相关的切片提供给代理，而不是整个代码库，既解决了上下文限制问题，也简化了代理的任务。因此，最佳的系统设计是利用静态分析作为代理的数据预处理器，而不是代理行动空间内的一个工具。这最大化了两种组件的优势：静态分析的规模化处理能力和LLM在受限上下文中的推理能力。

---

## **第四节：综合分析与推荐研究路线图**

本节将前述的优化建议整合为一个有优先级的、可操作的计划。目标是提供一条从基线SWE-Agent到一个高度专业化且有效的PoC生成代理的清晰路径，以契合项目对效率和显著影响力的要求。

### **4.1 改进路径的比较分析**

本小节将对三个核心改进领域进行详细分析，并根据您的标准进行评估。它将综合前几节的发现，并以清晰的比较格式呈现，辅以下表。讨论将强调，这些并非相互排斥的路径，而是协同增效的能力层。最高的投资回报率来自基础的反馈循环，因为它能使更高级的推理技术有效运作。

#### **表4.1：代理增强提案的优先级评估**

此表作为一个战略决策工具，总结了每个提议改进方向的权衡。

| 改进方向 | 实施难易度 | 对精确错误复现的潜在影响 | 关键依赖/先决条件 | 相关研究 |
| :---- | :---- | :---- | :---- | :---- |
| **第一层：基础能力** |  |  |  |  |
| 专用ACI（调试器和消毒剂解析器） | 中等 | 高 | SWE-ReX支持有状态会话；调试器脚本能力（如Python的pexpect）；结构化日志解析。 | \[2, 3, 4, 5\] |
| 动态分析反馈循环 | 中等 | **非常高** | 专用的ACI；修改代理主循环以处理结构化反馈。 | \[6, 7\] |
| **第二层：高级推理** |  |  |  |  |
| 轻量级反思循环 | 中到高 | **非常高** | 一个功能完备的动态反馈循环；用于自我批判的高级提示工程。 | \[9, 10, 12\] |
| 结构化假设管理 | 高 | 高 | 一个功能完备的反思循环；用于假设生成和规划的提示工程。 | \[15, 16, 17\] |
| **第三层：效率与扩展** |  |  |  |  |
| 程序切片与污点分析（作为预处理） | 高 | **非常高** | 集成外部工具（如Joern, CodeQL）；一个用于运行分析并为提示格式化输出的流水线。 | \[20, 21, 22, 23\] |

### **4.2 PoC代理的分阶段实施计划**

#### **第一阶段：构建“感官”（第1-2周）**

这是绝对的首要任务。

* **焦点**：完全专注于第一节的内容。  
* **目标**：修改SWE-Agent，集成GDB和消毒剂解析器工具。建立高保真动态反馈循环。  
* **成功指标**：代理能够执行一个程序，接收一个代表消毒剂报告的崩溃的结构化JSON对象，并且该数据在其下一个回合的上下文中可用。

#### **第二阶段：教会代理“思考”（第3-4周）**

在第一阶段的基础上，实施第二节的推理框架。

* **焦点**：构建认知能力。  
* **目标**：集成融合了反思与假设的认知循环。  
* **成功指标**：通过分析代理的行动轨迹，可以观察到代理不再是暴力破解解决方案，而是在生成明确的假设，测试它们，并利用自我反思来纠正其路线。这应导致解决任务所需的尝试次数出现可衡量的减少。

#### **第三阶段：赋予代理“专注力”（第5-6周）**

拥有一个会思考的代理后，重点转向效率。

* **焦点**：优化上下文和成本。  
* **目标**：实施第三节的静态分析预处理流水线。  
* **成功指标**：每个任务的令牌数量减少一个数量级。代理能够解决以前因上下文大小限制而无法处理的、复杂的多文件漏洞。此阶段使解决方案具有可扩展性和成本效益。

这个分阶段的计划提供了一个清晰、可管理且逻辑连贯的进展路径，确保每个阶段都建立在坚实的基础上，并能交付切实的价值，从而直接满足了对高效、有效的研发策略的需求。

#### **引用的著作**

1. SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering \- NIPS papers, 访问时间为 十一月 3, 2025， [https://proceedings.neurips.cc/paper\_files/paper/2024/file/5a7c947568c1b1328ccc5230172e1e7c-Paper-Conference.pdf](https://proceedings.neurips.cc/paper_files/paper/2024/file/5a7c947568c1b1328ccc5230172e1e7c-Paper-Conference.pdf)  
2. Architecture \- SWE-agent documentation, 访问时间为 十一月 3, 2025， [https://swe-agent.com/latest/background/architecture/](https://swe-agent.com/latest/background/architecture/)  
3. SWE-agent/SWE-ReX: Sandboxed code execution for AI agents, locally or on the cloud. Massively parallel, easy to extend. Powering SWE-agent and more. \- GitHub, 访问时间为 十一月 3, 2025， [https://github.com/SWE-agent/SWE-ReX](https://github.com/SWE-agent/SWE-ReX)  
4. ChatDBG: Augmenting Debugging with Large Language Models \- arXiv, 访问时间为 十一月 3, 2025， [https://arxiv.org/html/2403.16354v3](https://arxiv.org/html/2403.16354v3)  
5. GDB \- LLM-Powered Debugging & Binary Analysis Tool \- MCP Market, 访问时间为 十一月 3, 2025， [https://mcpmarket.com/server/gdb](https://mcpmarket.com/server/gdb)  
6. Vibe Coding: Closing The Feedback Loop With Traceability | Product Blog • Sentry, 访问时间为 十一月 3, 2025， [https://blog.sentry.io/vibe-coding-closing-the-feedback-loop-with-traceability/](https://blog.sentry.io/vibe-coding-closing-the-feedback-loop-with-traceability/)  
7. LDB: A Large Language Model Debugger via Verifying Runtime Execution Step by Step, 访问时间为 十一月 3, 2025， [https://arxiv.org/html/2402.16906v2](https://arxiv.org/html/2402.16906v2)  
8. SWE-agent/mini-swe-agent: The 100 line AI agent that solves GitHub issues or helps you in your command line. Radically simple, no huge configs, no giant monorepo—but scores \>70% on SWE-bench verified\! \- GitHub, 访问时间为 十一月 3, 2025， [https://github.com/SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)  
9. Reflexion | Prompt Engineering Guide, 访问时间为 十一月 3, 2025， [https://www.promptingguide.ai/techniques/reflexion](https://www.promptingguide.ai/techniques/reflexion)  
10. Reflexion: Language Agents with Verbal ... \- OpenReview, 访问时间为 十一月 3, 2025， [https://openreview.net/pdf?id=vAElhFcKW6](https://openreview.net/pdf?id=vAElhFcKW6)  
11. Reflexion: Language Agents with Verbal Reinforcement Learning \- Princeton University, 访问时间为 十一月 3, 2025， [https://collaborate.princeton.edu/en/publications/reflexion-language-agents-with-verbal-reinforcement-learning-2](https://collaborate.princeton.edu/en/publications/reflexion-language-agents-with-verbal-reinforcement-learning-2)  
12. Reflection Agents \- LangChain Blog, 访问时间为 十一月 3, 2025， [https://blog.langchain.com/reflection-agents/](https://blog.langchain.com/reflection-agents/)  
13. What is Tree Of Thoughts Prompting? \- IBM, 访问时间为 十一月 3, 2025， [https://www.ibm.com/think/topics/tree-of-thoughts](https://www.ibm.com/think/topics/tree-of-thoughts)  
14. www.ibm.com, 访问时间为 十一月 3, 2025， [https://www.ibm.com/think/topics/tree-of-thoughts\#:\~:text=Tree%20of%20thoughts%20(ToT)%20is,to%20a%20tree's%20branching%20paths.](https://www.ibm.com/think/topics/tree-of-thoughts#:~:text=Tree%20of%20thoughts%20\(ToT\)%20is,to%20a%20tree's%20branching%20paths.)  
15. Tree of Thoughts (ToT) \- Prompt Engineering Guide, 访问时间为 十一月 3, 2025， [https://www.promptingguide.ai/techniques/tot](https://www.promptingguide.ai/techniques/tot)  
16. \[2510.08619\] Hypothesis Hunting with Evolving Networks of Autonomous Scientific Agents \- arXiv, 访问时间为 十一月 3, 2025， [https://arxiv.org/abs/2510.08619](https://arxiv.org/abs/2510.08619)  
17. tmgthb/Autonomous-Agents: Autonomous Agents (LLMs) research papers. Updated Daily. \- GitHub, 访问时间为 十一月 3, 2025， [https://github.com/tmgthb/Autonomous-Agents](https://github.com/tmgthb/Autonomous-Agents)  
18. Introducing Open SWE: An Open-Source Asynchronous Coding Agent \- LangChain Blog, 访问时间为 十一月 3, 2025， [https://blog.langchain.com/introducing-open-swe-an-open-source-asynchronous-coding-agent/](https://blog.langchain.com/introducing-open-swe-an-open-source-asynchronous-coding-agent/)  
19. From LLMs to LLM-based Agents for Software Engineering: A Survey of Current, Challenges and Future \- arXiv, 访问时间为 十一月 3, 2025， [https://arxiv.org/html/2408.02479v1](https://arxiv.org/html/2408.02479v1)  
20. PoCGen: Generating Proof-of-Concept Exploits for Vulnerabilities in Npm Packages \- arXiv, 访问时间为 十一月 3, 2025， [https://arxiv.org/html/2506.04962v3](https://arxiv.org/html/2506.04962v3)  
21. LLMxCPG: Context-Aware Vulnerability Detection Through Code Property Graph-Guided Large Language Models \- USENIX, 访问时间为 十一月 3, 2025， [https://www.usenix.org/system/files/usenixsecurity25-lekssays.pdf](https://www.usenix.org/system/files/usenixsecurity25-lekssays.pdf)  
22. On the effects of program slicing for vulnerability detection during code inspection \- NIH, 访问时间为 十一月 3, 2025， [https://pmc.ncbi.nlm.nih.gov/articles/PMC11972194/](https://pmc.ncbi.nlm.nih.gov/articles/PMC11972194/)  
23. On the Effects of Program Slicing for Vulnerability Detection during Code Inspection: Extended Abstract | Request PDF \- ResearchGate, 访问时间为 十一月 3, 2025， [https://www.researchgate.net/publication/380837495\_On\_the\_Effects\_of\_Program\_Slicing\_for\_Vulnerability\_Detection\_during\_Code\_Inspection\_Extended\_Abstract](https://www.researchgate.net/publication/380837495_On_the_Effects_of_Program_Slicing_for_Vulnerability_Detection_during_Code_Inspection_Extended_Abstract)  
24. SliceMate: Accurate and Scalable Static Program Slicing via LLM-Powered Agents \- arXiv, 访问时间为 十一月 3, 2025， [https://arxiv.org/html/2507.18957v1](https://arxiv.org/html/2507.18957v1)  
25. MultiGLICE: Combining Graph Neural Networks and Program Slicing for Multiclass Software Vulnerability Detection \- Radboud Repository, 访问时间为 十一月 3, 2025， [https://repository.ubn.ru.nl/bitstream/handle/2066/317294/317294.pdf?sequence=1](https://repository.ubn.ru.nl/bitstream/handle/2066/317294/317294.pdf?sequence=1)