# SMAR论文内容总结报告

> **生成日期**：2025年  
> **信息来源**：网络学术搜索

---

## 一、概述：SMAR在学术领域的多重含义

"SMAR"在学术界并非单一概念，根据网络搜索结果，至少存在**四种主要的不同学术定义**，分别归属于信息检索、推荐系统、科研工具等不同研究领域。本报告对这四种SMAR含义逐一进行详细总结。

---

## 二、SMAR含义之一：Semantic-enhanced Modality-Asymmetric Retrieval（语义增强的模态不对称检索）

### 2.1 基本信息

| 项目 | 内容 |
|------|------|
| **全称** | Semantic-enhanced Modality-Asymmetric Retrieval |
| **缩写** | SMAR |
| **应用场景** | 在线电商搜索（Online E-commerce Search） |
| **发布来源** | SIGIR 2023（International ACM SIGIR Conference） |
| **作者团队** | 京东（JD.com）搜索与推荐部门：Zhigong Zhou, Ning Ding, Xiaochuan Fan, Han Zhang |
| **论文链接** | https://arxiv.org/abs/2506.20330 |
| **开源数据集** | https://github.com/jdcomsearch/jd-multimodal-data |

### 2.2 核心研究问题

传统的电商搜索中的语义检索主要依赖**文本信息**，但商品通常包含**图像等多模态信息**。利用图像作为文本信息的补充可以丰富商品表示，提升检索性能，尤其是在文本信息不足或存在歧义的情况下。

该研究聚焦于**模态不对称场景**：
- **查询（Query）**：单模态（纯文本）
- **商品（Item）**：多模态（文本 + 图像）

这带来了两个主要挑战：

1. **模态融合（Modality Fusion）**：如何有效融合多模态信息，既避免冗余又能捕获补充信息
2. **不对称对齐（Asymmetric Alignment）**：如何解决单模态查询与多模态商品之间的不对称对齐问题

### 2.3 模型架构

SMAR基于标准的**双塔（Two Tower）嵌入模型架构**进行扩展，包含四个核心组成部分：

- **Query Tower（查询塔）**：编码文本查询
- **Item Text Tower（商品文本塔）**：编码商品的文本特征（标题、品类、品牌等）
- **Item Image Tower（商品图像塔）**：编码商品图像特征
- **Item Multimodal Tower（商品多模态塔）**：通过交叉注意力（Cross Attention）机制融合文本和图像

模型采用Transformer编码器处理文本和图像两种模态的信息。

### 2.4 两阶段训练策略

#### 阶段一：基于多任务学习的预训练（Pre-training）

包含三个训练任务：
1. **语义投影任务（Semantic Projection）**：学习查询与商品之间的文本模态语义相似度
2. **模态对齐任务（Modality Alignment）**：学习查询文本与商品图像之间的对齐
3. **不对称模态对齐任务（Asymmetric Modality Alignment）**：学习查询文本与商品多模态表示之间的对齐

损失函数设计：
`L(D) = α·L_t(D) + β·L_i(D) + γ·L_m(D)`

其中 α, β, γ 是超参数，用于平衡不同模态的贡献。训练数据通过Batch Negative Sampling采样策略扩充生成负例。

#### 阶段二：基于自适应嵌入学习的微调（Fine-tuning）

- 微调阶段旨在根据查询或商品类别**自适应地决定是否引入图像信息**
- 引入**Prediction Header P**来预测"是否引入图像信息"
- 当 P(q)=1 时，使用多模态嵌入；当 P(q)=0 时，使用纯文本嵌入
- 图像信息对商品表示的贡献是**动态且自适应**的
- 微调阶段使用用户点击日志作为训练数据

### 2.5 实验结果

#### 离线实验指标

数据集：采样自60天用户点击日志，包含Overall、Fashion和Not-fashion三个子集，共计2,163,445个样本、373,343个查询、957,842个商品。

关键指标对比（Overall数据集，Recall@50）：

| 模型 | R@50 | P@50 | F1@50 |
|------|------|------|-------|
| DPSR-i（纯图像） | 0.349 | 0.018 | 0.034 |
| DPSR（纯文本基线） | 0.641 | 0.031 | 0.059 |
| **SMAR** | **0.690** | **0.033** | **0.063** |

**离线实验核心结论**：
- SMAR在所有数据集上显著优于基线模型
- 在Overall数据集上 R@50 提升 **4.90%**，P@50 提升 **1.50%**
- 多任务预训练目标对不对称模态对齐有效
- Cross Attention机制对模态融合至关重要

#### 在线A/B测试

在15%的在线流量上进行A/B测试，与成熟电商搜索系统对比：

| 指标 | SMAR整体 | SMAR在Fashion品类 |
|------|---------|-----------------|
| GMV（商品交易总额） | +0.285% | **+1.112%** |
| UCVR（用户转化率） | +0.174% | **+0.437%** |

### 2.6 结论与应用价值

SMAR模型通过两阶段训练策略有效解决了电商搜索中的模态不对称检索问题。该模型已在京东在线电商搜索系统中部署并服务主要流量，在GMV和用户转化率方面均带来显著提升，尤其是在Fashion品类中效果尤为突出。

---

## 三、SMAR含义之二：Single-modal supervision for Modal-wise relevance Alignment in Reranking（单模态监督的模态相关性对齐重排序）

### 3.1 基本信息

| 项目 | 内容 |
|------|------|
| **全称** | Single-modal supervision for Modal-wise relevance Alignment in Reranking |
| **缩写** | SMAR |
| **应用场景** | 搜索引擎全页面重排序（Whole-Page Reranking） |
| **发布来源** | arXiv 2025年10月 |
| **作者团队** | 北京航空航天大学 + 百度（Baidu Inc.）|
| **论文链接** | https://arxiv.org/abs/2510.16803 |
| **开源代码** | https://github.com/zzs97str/SMAR |

### 3.2 核心研究问题

搜索引擎已演变为整合文本、图像、视频和LLM输出等多模态信息的复杂平台。**全页面重排序**在确定异构结果的最终排序和呈现方面至关重要，需要平衡相关性、一致性和用户满意度等多种信号。

现有方法主要依赖**大规模人工标注数据**，但全页面标注需要评估整个结果页面的全局排序质量并考虑跨模态的相关性差异，成本高昂且耗时。SMAR框架旨在以极低的标注成本实现高质量的全页面重排序。

### 3.3 SMAR框架核心方法

#### 单模态排序器监督（Single-modal Ranker Supervision）

- 将上游单模态排序器为各模态内条目分配的分数转化为监督信号
- 支持两种监督方案：
  - **Pairwise supervision（成对监督）**：成对损失函数 L_m = y_ij · max(0, γ - (f(u,q,i) - f(u,q,j)))
  - **Listwise supervision（列表级监督）**：使用KL散度或ListMLE损失

#### 预算感知标注策略（Budget-aware Annotation Strategy）

两种策略应对有限标注预算：
1. **Top-P策略**：仅标注每个模态内得分最高的top-p比例部分，其余部分由上游分数弱监督
2. **等标签锚点策略（Iso-label Anchors）**：通过二分搜索在不同模态间找到分数相近的条目作为锚点，对齐偏好尺度

#### 全页面重排序器架构

- 采用结合用户特征的**Cross-Attention机制**
- **混合融合（Hybrid Fusion）**：早期融合 + 晚期融合门控机制
- 使用ListMLE损失函数进行训练

### 3.4 实验结果

#### 数据集
- **Qilin数据集**：小红书（Red Book APPs），15,000+用户，1,900,000条笔记，5,000,000张图片
- **DuRank数据集**：百度发布的高质量标注数据集，15,000+查询，300,000+检索结果

#### 主要结果（DuRank数据集 - BERT-Base-Chinese）

| 方法 | 标注量 | MRR@1 | NDCG |
|------|--------|-------|------|
| SFT（全量监督） | 100%数据 | 0.7414 | 0.6870 |
| **SMAR** | 仅10%数据 | **0.7526** | **0.6947** |
| **SMAR** | 仅30%数据 | **0.7586** | 0.6952 |

#### 核心结论

- **大幅降低标注成本**：减少标注成本约 **70-90%**
- **超越全量监督**：仅用10%标注数据即可超越使用100%数据训练的基线模型（SFT）
- **在线收益显著**：在百度APP在线A/B测试中，NDCG提升0.86%，CTR提升0.25%
- **用户体验改善**：ΔGSB提升1.58%，次日留存用户提升0.33%

### 3.5 研究意义

SMAR框架首次提出了利用单模态监督信号来指导多模态全页面重排序的新范式，通过知识蒸馏和预算感知标注策略，以极低的标注成本实现了超越全量监督的性能，对于降低搜索引擎排序系统的维护成本具有重要价值。

---

## 四、SMAR含义之三：Self-supervised Mobile Application Recommendation（自监督移动应用推荐）

### 4.1 基本信息

| 项目 | 内容 |
|------|------|
| **全称** | Self-supervised Mobile Application Recommendation based on Graph Convolutional Networks |
| **缩写** | SMAR |
| **应用场景** | 移动应用推荐系统 |
| **发布期刊** | International Journal of Web Information Systems (Emerald) |
| **论文链接** | https://www.emerald.com/ijwis/article/20/5/520/1222452/SMAR-self-supervised-mobile-application |

### 4.2 核心方法

- 基于**图卷积网络（Graph Convolutional Networks, GCN）**构建用户-应用交互图
- 结合**自监督学习（Self-supervised Learning）**进行移动应用推荐
- 旨在克服现有推荐系统中的数据稀疏性问题

### 4.3 研究背景与挑战

推荐系统面临的主要挑战：
1. **数据稀疏性**：用户与应用的交互数据非常稀疏，模型难以学到有效表示
2. **冷启动问题**：新应用或新用户缺乏交互历史，难以获得推荐
3. **长尾分布**：热门应用主导推荐，长尾应用难以被推荐

SMAR通过自监督学习从用户-应用交互图中挖掘额外的监督信号，有效缓解上述问题。

### 4.4 技术关联

该SMAR方法与SGL（Self-supervised Graph Learning for Recommendation，SIGIR 2021）有密切的技术关联。SGL提出的方法包括：

- **三种数据增强算子**：节点丢弃（Node Dropout）、边丢弃（Edge Dropout）、随机游走（Random Walk）
- **对比学习**：最大化同一节点在不同视图间的一致性
- **理论分析**：自监督对比学习具有挖掘难负样本（Hard Negative Mining）的内禀能力

SGL在Yelp2018、Amazon-Book、Alibaba-iFashion三个数据集上验证了有效性，在长尾推荐和抗噪声方面表现突出。SMAR在此基础上做了针对移动应用推荐领域的适配和优化。

---

## 五、SMAR含义之四：Systematic App Store Reviews Project（系统应用商店评论分析工具）

### 5.1 基本信息

| 项目 | 内容 |
|------|------|
| **全称** | Systematic App Store Reviews (SMAR) Project |
| **应用场景** | 协助非技术研究人员进行系统应用商店评论分析 |
| **官方网站** | https://smar-tool.org/about |

### 5.2 项目描述

SMAR Project旨在协助**非技术研究人员**进行"系统应用商店评论分析"（Systematic App Store Reviews），该过程通常包括：

- **爬取（Scraping）**：自动收集应用商店评论数据
- **分析（Analysis）**：对评论数据进行系统分析，提取有用信息
- **可视化（Visualization）**：以直观方式呈现分析结果
- **工具接口**：为研究人员提供易用的工具接口，降低技术门槛

该项目降低了非计算机领域研究人员分析应用评论的技术门槛，促进了跨学科研究的发展。

---

## 六、总结对比

### 四种SMAR含义的横向对比

| SMAR含义 | 全称 | 研究领域 | 核心贡献 | 来源 |
|---------|------|---------|---------|------|
| **SMAR-1** | Semantic-enhanced Modality-Asymmetric Retrieval | 电商搜索/信息检索 | 两阶段训练的模态不对称检索模型，GMV提升1.112% | SIGIR 2023 / 京东 |
| **SMAR-2** | Single-modal supervision for Modal-wise relevance Alignment in Reranking | 搜索引擎/重排序 | 低成本全页面重排序框架，减少70-90%标注成本 | arXiv 2025 / 百度+北航 |
| **SMAR-3** | Self-supervised Mobile Application Recommendation | 推荐系统 | 基于GCN的自监督移动应用推荐，缓解数据稀疏性 | IJWIS / Emerald |
| **SMAR-4** | Systematic App Store Reviews Project | 科研工具 | 非技术研究人员做应用商店评论分析的辅助工具 | smar-tool.org |

### 研究趋势分析

从这四种SMAR含义可以看出当前学术研究的几个重要趋势：

1. **多模态融合**：SMAR-1和SMAR-2都聚焦于多模态信息的融合与对齐，体现了信息检索领域从纯文本向多模态发展的趋势
2. **降低标注成本**：SMAR-2通过知识蒸馏和弱监督策略大幅降低标注成本，反映了学术界对降低AI应用门槛的追求
3. **自监督学习**：SMAR-3利用自监督学习缓解数据稀疏性问题，代表推荐系统领域的前沿方向
4. **跨学科工具**：SMAR-4展示了学术研究向非技术领域渗透的趋势，赋能更多研究者

---

## 七、关键参考文献

1. Zhou, Z., Ding, N., Fan, X., & Zhang, H. (2023). Semantic-enhanced Modality-asymmetric Retrieval for Online E-commerce Search. *SIGIR 2023*. arXiv:2506.20330.

2. Zhang, Z., Yu, S., Xie, W., Nie, Y., Wang, J., Zheng, Z., Yin, D., & Zhang, H. (2025). An Efficient Framework for Whole-Page Reranking via Single-Modal Supervision. arXiv:2510.16803.

3. SMAR: self-supervised mobile application recommendation based on graph convolutional networks. *International Journal of Web Information Systems*, Vol. 20 No. 5.

4. Wu, J., Wang, X., Feng, F., He, X., Chen, L., Lian, J., & Xie, X. (2021). Self-supervised Graph Learning for Recommendation. *SIGIR 2021*.

5. SMAR Project. Systematic App Store Reviews. https://smar-tool.org/about

---

*本报告基于网络搜索结果整理生成，内容由SMAR相关学术论文信息综合而成。*