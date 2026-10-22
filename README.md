# 配置虚拟环境
强烈推荐使用虚拟环境运行本项目
你需要创建自己的虚拟环境，并且虚拟环境请命名为**venv**,并且不要上传到github中

项目现在使用uv作为包管理器
# UV
## 安装依赖
```
uv sync
```

# 运行项目
## 配置env数据
当前代码支持接入Deepseek flash，需要配置deepseek的API KEY

在根目录中创建`.evn`文件，在文件中输入`DEEPSEEK_API_KEY=你的API KEY`


# PI
RAG能力依赖Pi-agent与Pi-knowledge, 请确保已经全局或者本地安装下面的依赖再运行项目
## 安装PI
```
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
```
## 安装PI-KNOWLEDGE
```
pi install npm:pi-knowledge
```