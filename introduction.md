---
description: A little bit about where we stand.
icon: anchor
cover: >-
  https://images.unsplash.com/photo-1584619147866-dcae38272c8e?crop=entropy&cs=srgb&fm=jpg&ixid=M3wxOTcwMjR8MHwxfHNlYXJjaHwyfHxjYXBlJTIwc3BsaXR8ZW58MHx8fHwxNzIyNjI1MjczfDA&ixlib=rb-4.0.3&q=85
coverY: 0
layout:
  width: default
  cover:
    visible: true
    size: full
  title:
    visible: true
  description:
    visible: true
  tableOfContents:
    visible: true
  outline:
    visible: true
  pagination:
    visible: true
  metadata:
    visible: true
  tags:
    visible: true
  actions:
    visible: true
---

# Introduction

## Overview

Welcome to [AISdb](https://github.com/MAPS-Lab/AISdb), a comprehensive gateway for [Automatic Identification System (AIS)](https://en.wikipedia.org/wiki/Automatic_identification_system) data use and applications. AISdb is part of the [Making Maritime Informatics Accessible to Everyone (AISViz)](https://github.com/MAPS-Lab) project, developed and maintained by the [MAPS Lab](https://mapslab.tech/) at [Dalhousie University](https://www.dal.ca/) and building on earlier work from the [MERIDIAN](https://meridian.cs.dal.ca/) initiative. It is designed to streamline the collection, processing, and analysis of AIS data, both in live-streaming scenarios and through historical records.

<table data-card-size="large" data-view="cards"><thead><tr><th></th><th></th><th data-hidden data-card-target data-type="content-ref"></th></tr></thead><tbody><tr><td><strong>Quick Start</strong></td><td>Install AISdb and run your first query on local data.</td><td><a href="default-start/quick-start.md">quick-start.md</a></td></tr><tr><td><strong>Docker Start</strong></td><td>Spin up AISdb in a container without a manual install.</td><td><a href="docker-start/quick-start.md">quick-start.md</a></td></tr><tr><td><strong>Tutorials</strong></td><td>Load AIS data into a database and start exploring it.</td><td><a href="tutorials/database-loading.md">database-loading.md</a></td></tr><tr><td><strong>Machine Learning</strong></td><td>Cluster vessel behavior with scikit-learn on AIS data.</td><td><a href="machine-learning/clustering-with-scikit-learn.md">clustering-with-scikit-learn.md</a></td></tr></tbody></table>

The primary features AISdb provides include the following.

### SQL database for storing AIS position reports and vessel metadata

At the heart of AISdb is a database built on [SQLite](https://www.sqlite.org/index.html), giving users a friendly Python interface with which to interact. This interface simplifies tasks like <mark style="background-color:yellow;">database creation, data querying, processing, visualization, and exporting data to CSV format</mark> for diverse uses. To cater to advanced needs, AISdb also supports [PostgreSQL](https://www.postgresql.org/), including an optional TimescaleDB extension, offering superior concurrency handling and data-sharing capabilities for collaborative environments.

<div align="left"><figure><img src=".gitbook/assets/image (26).png" alt=""><figcaption></figcaption></figure></div>

### Vessel data cleaning and trajectory modeling

AISdb includes <mark style="background-color:yellow;">vessel position cleaning and trajectory modeling features</mark>. This ensures that the data used for analyses is accurate and reliable, providing a solid foundation for further studies and applications.

### Integration with environmental context and external metadata

One of AISdb's unique features is its ability to enrich AIS datasets with environmental context. Users can seamlessly integrate oceanographic and bathymetric data in raster formats to bring depth to their analyses, quite literally, as the tool allows for incorporating seafloor depth data underneath vessel positions. Such versatility ensures that AISdb users can merge various environmental data points with AIS information, resulting in richer, multi-faceted maritime studies.

### Advanced features for maritime studies

AISdb offers <mark style="background-color:yellow;">network graph analysis, MMSI deduplication, interpolation, and other processing utilities</mark>. These features enable advanced data processing and analysis, supporting complex maritime studies and applications.

### Python interface and machine learning for vessel behavior modeling

AISdb includes a Python interface with a Rust core, built through PyO3 and Maturin, that paves the way for incorporating machine learning and deep learning techniques into vessel behavior modeling in an optimized way. This aspect of AISdb enhances the reproducibility and scalability of research, be it for academic exploration or practical industry applications.

### Research support

AISdb is more than just a storage and processing tool. It is a comprehensive platform designed to support research. <mark style="background-color:yellow;">Through a formal partnership with our research initiative</mark> (contact us for more information), academics, industry experts, and researchers can access extensive Canadian AIS data up to 100 km from the Canadian coastline. This dataset spans from January 2012 to the present and is updated monthly. AISdb offers raw and parsed data formats, eliminating preprocessing needs and streamlining AIS-related research.

The MAPS Lab team is based in the [Modeling and Analytics for Predictive Systems (MAPS)](https://mapslab.tech/) lab in collaboration with the [Maritime Risk and Safety (MARS)](https://www.maritimeriskandsafety.ca/) research group at Dalhousie University. Our team is funded by the [Department of Fisheries and Oceans Canada (DFO)](https://www.dfo-mpo.gc.ca/index-eng.html), and our <mark style="background-color:yellow;">mission revolves around democratizing AIS data use, making it accessible and understandable across multiple sectors, from government and academia to NGOs and the broader public</mark>. In addition, AISViz aims to introduce machine learning applications into AISdb's AIS data handling. This effort seeks to streamline user interactions with AIS data, enhancing the user experience by simplifying data access.

Our commitment goes beyond just providing tools. Through AISViz, we're opening doors to innovative research and policy development, targeting environmental conservation, maritime traffic management, and much more. Whether you're a professional in the field, an educator, or a maritime enthusiast, AISViz and its components, including AISdb, offer the knowledge and technology to deepen your understanding and significantly impact marine vessel tracking and the well-being of our oceans.

## Our Team

#### Active Members

* **Ruixin Song** is a research assistant in the Computer Science Department at Dalhousie University. She has an M.Sc. in Computer Science and a B.Eng. in Spatial Information and Digital Technology. Her recent work focuses on marine traffic data analysis and physics-inspired models, particularly in relation to biological invasions in the ocean. Her research interests include mobility data mining, graph neural networks, and network flow and optimization problems.
  * **Contact:** [rsong@dal.ca](mailto:rsong@dal.ca)
* **Gabriel Spadon** is an Assistant Professor at the Faculty of Computer Science at Dalhousie University, Halifax - NS, Canada. He holds a Ph.D. and an MSc in Computer Science from the University of Sao Paulo, Sao Carlos - SP, Brazil. His research focuses on spatio-temporal analytics, time-series forecasting, and complex network mining, with a deep involvement in data science and engineering, as well as geoinformatics.
  * **Contact:** [spadon@dal.ca](mailto:spadon@dal.ca)
* **Ron Pelot** has a Ph.D. in Management Sciences and is a Professor of Industrial Engineering at Dalhousie University. For the last 30 years, he and his team have been working on developing new software tools and analysis methods for maritime traffic safety, coastal zone security, and marine spills. Their research methods include spatial risk analysis, vessel traffic modeling, data processing, pattern analysis, location models for response resource allocation, safety analyses, and cumulative shipping impact studies.
  * **Contact:** [ronald.pelot@dal.ca](mailto:ronald.pelot@dal.ca)

#### Adjunct Members

* **Vaishnav Vaidheeswaran** is a Master's student in Computer Science at Dalhousie University. He holds a B.Tech in Computer Science and Engineering and has three years of experience as a software engineer in India, working at cutting-edge startups. His ongoing work focuses on incorporating spatial knowledge into trajectory forecasting models to reduce the aleatoric uncertainty arising from stochastic interactions between the vessel and the environment. His research interests include large language models, graph neural networks, and reinforcement learning.
  * **Contact:** [vaishnav@dal.ca](mailto:vaishnav@dal.ca)
* **Parth Doshi** is a Bachelor's student in Computer Science at Dalhousie University. His ongoing work focuses on developing a Generative Adversarial Network that generates vessel trajectories through agents, as well as on vessel spoofing detection. His research interests include time-series-based forecasting and inverse reinforcement learning.
  * **Contact:** [parth.doshi@dal.ca](mailto:parth.doshi@dal.ca)

#### Former Members

* **Jinkun Chen** is a Ph.D. student in Computer Science at Dalhousie University, specializing in Explainable AI, Natural Language Processing (NLP), and Visualization. He earned a bachelor's degree in Computer Science with First-Class Honours from Dalhousie University. Jinkun is actively involved in research, working on advancing fairness, responsibility, trustworthiness, and explainability within Large Language Models (LLMs) and AI.
* **Jay Kumar** has a Ph.D. in Computer Science and Technology and was a postdoctoral fellow at the Department of Industrial Engineering at Dalhousie University. He has researched AI models for time-series data for over five years, focusing on Recurrent Neural models, probabilistic modeling, and feature engineering data analytics applied to ocean traffic. His research interests include Spatio-temporal Data Mining, Stochastic Modeling, Machine Learning, and Deep Learning.
* **Matthew Smith** has a BSc degree in Applied Computer Science from Dalhousie University and specializes in managing and analyzing vessel tracking data. He is currently a Software Engineer at Radformation in Toronto, ON. Matt served as the AIS data manager on the MERIDIAN project, where he supported research groups across Canada in accessing and utilizing AIS data. The data was used to answer a range of scientific queries, including the impact of shipping on underwater noise pollution and the danger posed to endangered marine mammals by vessel collisions.
* **Casey Hilliard** has a BSc degree in Computer Science from Dalhousie University and was a Senior Data Manager at the Institute for Big Data Analytics. He is currently a Chief Architect at GSTS (Global Spatial Technology Solutions) in Dartmouth, NS. Casey was a long-time research support staff member at the Institute and an expert in managing and using AIS vessel-tracking data. During his time, he assisted in advancing the Institute's research projects by managing and organizing large datasets, ensuring data integrity, and facilitating data usage in research.
* **Stan Matwin** was the director of the Institute for Big Data Analytics, Dalhousie University, Halifax, Nova Scotia; he is a professor and Canada Research Chair (Tier 1) in Interpretability for Machine Learning. He is also a distinguished professor (Emeritus) at the University of Ottawa and a full professor with the Institute of Computer Science, Polish Academy of Sciences. His main research interests include big data, text mining, machine learning, and data privacy. He is a member of the Editorial Boards of IEEE Transactions on Knowledge and Data Engineering and the Journal of Intelligent Information Systems. He received the Lifetime Achievement Award of the Canadian AI Association (CAIAC).

## **Contact**

We are passionate about fostering a collaborative and engaged community. We welcome your questions, insights, and feedback as vital components of our continuous improvement and innovation. Should you have any inquiries about AISdb, desire further information on our research, or wish to explore potential collaborations, please don't hesitate to contact us. Staying connected with users and researchers plays a crucial role in shaping the tool's development and ensuring it meets the diverse needs of our growing user base. You can easily contact our team via email or our [GitHub team platform](https://github.com/MAPS-Lab). <mark style="background-color:yellow;">In addition to addressing individual queries, we organize webinars and workshops and present at conferences to share knowledge, gather feedback, and widen our outreach.</mark> Together, let's advance the understanding and utilization of marine data for a brighter, more informed future in ocean research and preservation.
