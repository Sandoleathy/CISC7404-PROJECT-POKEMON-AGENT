# 配置虚拟环境
强烈推荐使用虚拟环境运行本项目
你需要创建自己的虚拟环境，并且虚拟环境请命名为**venv**,并且不要上传到github中
## 创建虚拟环境
```
python -m venv venv
```
## 进入虚拟环境
```
venv\Scripts\activate
```
# 安装依赖
```
pip install -r requirements.txt
```

# 运行项目
## 配置env数据
当前代码支持接入Deepseek flash，需要配置deepseek的API KEY

在根目录中创建`.evn`文件，在文件中输入`DEEPSEEK_API_KEY=你的API KEY`


## 运行Python脚本


输入`python deepseek_flash_player.py`使用deepseek玩游戏