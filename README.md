# 配置虚拟环境
强烈推荐使用虚拟环境运行本项目
你需要创建自己的虚拟环境，并且虚拟环境请命名为**venv**,并且不要上传到github中
## 创建虚拟环境
```
python -m venv venv
```
## 进入虚拟环境
```
venv\Script\activate
```
# 安装依赖
```
pip install -r requirements.txt
```

# 运行项目
运行本项目需要启动一个本地的pokemon showdown! 项目
## 安装Pokemon Showdown!
请先检查你的Node和Python版本
```
node -v      # 需要 v22.18.0 或更高
python -V    # 需要 3.10 或更高
```
## 克隆Showdown! 仓库
```
git clone https://github.com/smogon/pokemon-showdown.git
cd pokemon-showdown
npm install
copy config\config-example.js config\config.js
```
## 启动Pokemon Showdown!
```
node pokemon-showdown start --no-security
```
浏览器打开 `http://localhost:8000`即可看到Pokemon showdown的界面

# 运行游戏
## 配置env数据
当前代码支持接入Deepseek flash，需要配置deepseek的API KEY

在根目录中创建`.evn`文件，在文件中输入`DEEPSEEK_API_KEY=你的API KEY`


## 运行Python脚本
在虚拟环境中输入`python first_battle.py`使用默认算法（非AI）游玩游戏


输入`python deepseek_flash_player.py`使用deepseek玩游戏