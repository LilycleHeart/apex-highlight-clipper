using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class ApexClipper : Form {
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    readonly List<string> files = new List<string>();
    ListBox queue;
    TextBox output, log;
    Label status, count, current;
    ProgressBar progress;
    Button add, folder, clear, browse, start, stop, open, resume;
    CheckBox cpu, verify, deleteSource, pipeline;
    NumericUpDown gap, pre, post, fps;
    ComboBox gpuLoad, scanMode;
    readonly ToolTip tips = new ToolTip();
    bool busy;
    Process worker;
    bool cancelled, completed;
    string resultDirectory;
    string stopRequestPath;
    int fileIndex, fileTotal, fileProgress;

    [STAThread] static void Main(string[] args) {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        if(args.Length==1 && args[0]=="--self-test") {
            using(var form=new ApexClipper(new string[0])) {form.SelfTest();}
            return;
        }
        Application.Run(new ApexClipper(args));
    }
    ApexClipper(string[] args) {
        Text = "Apex 自动交战剪辑 · 智能识别与续接";
        ClientSize = new Size(930,710);
        MinimumSize = new Size(946,749);
        Font = new Font("Microsoft YaHei UI",10);
        AutoScaleMode = AutoScaleMode.Dpi;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(246,247,249);
        var title = new Label { Text="Apex 自动交战剪辑",Font=new Font(Font.FontFamily,19,FontStyle.Bold),Location=new Point(24,18),AutoSize=true };
        Controls.Add(title);
        Controls.Add(new Label { Text="保留交战与拉扯 · 每段独立无损 · 日期 / 击杀 / 枪械 / 伤害命名",Location=new Point(26,61),AutoSize=true });
        add=ButtonAt("添加录像",24,99,120,delegate { AddFiles(); });
        folder=ButtonAt("添加文件夹",154,99,130,delegate { AddFolder(); });
        clear=ButtonAt("清空列表",294,99,120,delegate { files.Clear(); RefreshQueue(); });
        count=new Label {Text="未选择录像",Location=new Point(435,107),AutoSize=true}; Controls.Add(count);
        queue=new ListBox {Location=new Point(24,143),Size=new Size(882,112),HorizontalScrollbar=true,IntegralHeight=false,Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right}; Controls.Add(queue);
        Controls.Add(new Label {Text="保存到",Location=new Point(24,278),AutoSize=true});
        output=new TextBox {Location=new Point(95,271),Size=new Size(691,28),Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right,Text=Path.Combine(root,"output","程序试剪")}; Controls.Add(output);
        browse=ButtonAt("选择目录",798,267,108,delegate {
            using(var dialog=new FolderBrowserDialog {Description="选择交战视频的保存目录"}) {
                if(dialog.ShowDialog(this)==DialogResult.OK) output.Text=dialog.SelectedPath;
            }
        }); browse.Anchor=AnchorStyles.Top|AnchorStyles.Right;
        cpu=new CheckBox {Text="使用 CPU",Location=new Point(24,313),Size=new Size(140,28),Checked=!File.Exists(Path.Combine(root,".gpu-venv","Scripts","python.exe"))}; Controls.Add(cpu);
        verify=new CheckBox {Text="校验无损输出（稍慢）",Location=new Point(175,313),Size=new Size(225,28),Checked=true}; Controls.Add(verify);
        deleteSource=new CheckBox {Text="输出后删除原录像（回收站）",Location=new Point(425,313),Size=new Size(360,28),Checked=false}; Controls.Add(deleteSource);
        deleteSource.CheckedChanged+=delegate { if(deleteSource.Checked) verify.Checked=true; verify.Enabled=!busy && !deleteSource.Checked; };
        tips.SetToolTip(deleteSource,"默认关闭。只有所有成片无损校验通过，且没有待复核候选或结束边界时，原录像才移入回收站。");
        gap=NumberAt("合并间隔（秒）",24,354,150,0,600,35);
        pre=NumberAt("前置（秒）",259,354,365,0,120,10);
        post=NumberAt("收尾（秒）",472,354,577,0,180,15);
        fps=NumberAt("细查帧/秒",684,354,797,0.5m,5,2);
        tips.SetToolTip(gap,"相邻交战信号间隔小于此值时合并；调大可保留更长拉扯，也会保留更多空档。");
        tips.SetToolTip(pre,"在首次交战信号前保留的秒数。");
        tips.SetToolTip(post,"末次信号后保留的秒数；倒地和队友交战仍按状态延长。");
        tips.SetToolTip(fps,"智能模式只在候选区间使用此频率，平稳区间约每8秒读取计分；完整模式整片使用此频率。默认2帧/秒。");
        Controls.Add(new Label {Text="GPU 档位",Location=new Point(24,399),AutoSize=true});
        gpuLoad=new ComboBox {Location=new Point(118,392),Size=new Size(145,30),DropDownStyle=ComboBoxStyle.DropDownList};
        gpuLoad.Items.AddRange(new object[]{"低占用","均衡","全速"}); gpuLoad.SelectedIndex=0; Controls.Add(gpuLoad);
        tips.SetToolTip(gpuLoad,"低占用：小批次推理、分批暂停、限速解码，给游戏留余量；占用百分比仍受显卡和其他程序影响。");
        Controls.Add(new Label {Text="识别方式",Location=new Point(283,399),AutoSize=true});
        scanMode=new ComboBox {Location=new Point(376,392),Size=new Size(198,30),DropDownStyle=ComboBoxStyle.DropDownList};
        scanMode.Items.AddRange(new object[]{"智能：变化后细查","完整：逐帧采样"}); Controls.Add(scanMode);
        tips.SetToolTip(scanMode,"智能模式先查关键帧的累计伤害、击杀、弹药和状态，变化后局部细查；有风险时回退补查。智能模式保留原片。完整模式用于对照及更多无伤害交火。");
        Controls.Add(new Label {Text="智能模式暂时保留原片",Location=new Point(596,398),AutoSize=true});
        start=ButtonAt("开始剪辑",24,432,140,delegate { StartJob(); });
        start.BackColor=Color.FromArgb(34,106,210); start.ForeColor=Color.White; start.FlatStyle=FlatStyle.Flat;
        stop=ButtonAt("停止",177,432,96,delegate { StopJob(); }); stop.Enabled=false;
        open=ButtonAt("打开结果目录",286,432,158,delegate { OpenResults(); }); open.Enabled=false;
        resume=ButtonAt("继续上次任务",458,432,160,delegate { ResumeLast(); });
        tips.SetToolTip(resume,"恢复原批次与输出目录，沿用原剪辑及删除选项；GPU/CPU 与 GPU 档位可调整。已完成的录像自动跳过。");
        resume.Enabled=LastTask()!=null;
        pipeline=new CheckBox {Text="解码 / 识别并行",Location=new Point(655,436),Size=new Size(250,28),Checked=true}; Controls.Add(pipeline);
        scanMode.SelectedIndexChanged+=delegate { if(scanMode.SelectedIndex==0) deleteSource.Checked=false; deleteSource.Enabled=!busy && scanMode.SelectedIndex==1; pipeline.Enabled=!busy && scanMode.SelectedIndex==1; };
        scanMode.SelectedIndex=0;
        tips.SetToolTip(pipeline,"默认开启。GPU 档位仍生效；若同时玩游戏时受影响，可以关闭以串行处理。断点、识别频率和剪辑规则不变。");
        current=new Label {Text="等待添加录像",Location=new Point(24,479),Size=new Size(882,25),AutoEllipsis=true,Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right}; Controls.Add(current);
        progress=new ProgressBar {Location=new Point(24,509),Size=new Size(882,18),Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right}; Controls.Add(progress);
        status=new Label {Text="就绪",Location=new Point(24,535),Size=new Size(882,25),AutoEllipsis=true}; Controls.Add(status);
        log=new TextBox {Location=new Point(24,566),Size=new Size(882,121),Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,BackColor=Color.White,Anchor=AnchorStyles.Top|AnchorStyles.Bottom|AnchorStyles.Left|AnchorStyles.Right}; Controls.Add(log);
        foreach(string arg in args) if(File.Exists(arg)) files.Add(Path.GetFullPath(arg));
        RefreshQueue();
        FormClosing+=delegate(object sender,FormClosingEventArgs e) {
            if(busy) {
                if(MessageBox.Show(this,"剪辑尚未完成，关闭窗口会停止本次任务。是否关闭？","停止剪辑",MessageBoxButtons.YesNo,MessageBoxIcon.Question)!=DialogResult.Yes) {e.Cancel=true;return;}
                StopJob();
            }
        };
    }
    Button ButtonAt(string text,int x,int y,int width,EventHandler action) {
        var button=new Button {Text=text,Location=new Point(x,y),Size=new Size(width,36)};
        button.Click+=action; Controls.Add(button); return button;
    }
    NumericUpDown NumberAt(string label,int x,int y,int numberX,decimal min,decimal max,decimal value) {
        Controls.Add(new Label {Text=label,Location=new Point(x,y+5),AutoSize=true});
        var number=new NumericUpDown {Location=new Point(numberX,y),Size=new Size(90,30),Minimum=min,Maximum=max,Value=value,DecimalPlaces=1,Increment=0.5m};
        Controls.Add(number); return number;
    }
    void SelfTest() {
        if(deleteSource.Checked || !verify.Checked || gap.Value!=35 || pre.Value!=10 || post.Value!=15 || fps.Value!=2 || gpuLoad.SelectedIndex!=0 || !pipeline.Checked || scanMode.SelectedIndex!=0) throw new Exception("默认参数不正确");
        if(deleteSource.Enabled || pipeline.Enabled) throw new Exception("智能模式不应启用删除或完整流水线选项");
        scanMode.SelectedIndex=1; verify.Checked=false; deleteSource.Checked=true;
        if(!verify.Checked || verify.Enabled) throw new Exception("开启回收未强制校验");
        SetBusy(true);
        if(deleteSource.Enabled || gap.Enabled || pre.Enabled || post.Enabled || fps.Enabled || gpuLoad.Enabled || resume.Enabled || pipeline.Enabled || scanMode.Enabled) throw new Exception("任务期间参数未锁定");
        SetBusy(false);
        if(verify.Enabled || !gap.Enabled) throw new Exception("任务结束后的参数状态不正确");
        deleteSource.Checked=false;
        if(!verify.Enabled) throw new Exception("关闭回收后校验不能调节");
        gap.Value=20; pre.Value=8; post.Value=10; fps.Value=3;
        PerformLayout();
        foreach(Control c in Controls) if(c.Right>ClientSize.Width || c.Bottom>ClientSize.Height) throw new Exception("控件超出窗口："+c.Text);
        string directory=Path.Combine(root,"validation","app-tests"); Directory.CreateDirectory(directory);
        File.WriteAllText(Path.Combine(directory,"ui-self-test.json"),json.Serialize(new {passed=true,defaults=true,delete_forces_verification=true,busy_locks_parameters=true,layout_fits=true}),new UTF8Encoding(false));
        gap.Value=35; pre.Value=10; post.Value=15; fps.Value=2; scanMode.SelectedIndex=0;
        CreateControl();
        using(var preview=new Bitmap(Width,Height)) {
            DrawToBitmap(preview,new Rectangle(0,0,Width,Height));
            preview.Save(Path.Combine(directory,"ui-preview.png"),System.Drawing.Imaging.ImageFormat.Png);
        }
    }
    void AddFiles() {
        using(var dialog=new OpenFileDialog {Title="选择 Apex 录像（可多选）",Filter="录像|*.mp4;*.mkv;*.mov;*.ts;*.m4v",Multiselect=true}) {
            if(dialog.ShowDialog(this)==DialogResult.OK) AddPaths(dialog.FileNames);
        }
    }
    void AddFolder() {
        using(var dialog=new FolderBrowserDialog {Description="添加文件夹第一层的录像"}) {
            if(dialog.ShowDialog(this)==DialogResult.OK) AddPaths(Directory.GetFiles(dialog.SelectedPath).Where(p=>new[]{".mp4",".mkv",".mov",".ts",".m4v"}.Contains(Path.GetExtension(p).ToLowerInvariant())));
        }
    }
    void AddPaths(IEnumerable<string> paths) {
        foreach(var path in paths) if(!files.Contains(path,StringComparer.OrdinalIgnoreCase)) files.Add(path);
        RefreshQueue();
    }
    void RefreshQueue() { queue.Items.Clear(); queue.Items.AddRange(files.ToArray()); count.Text=files.Count+" 段录像"; }
    void SetBusy(bool busy) {
        this.busy=busy;
        foreach(Control c in new Control[]{add,folder,clear,browse,start,output,cpu,gap,pre,post,fps,gpuLoad,scanMode,queue}) c.Enabled=!busy;
        deleteSource.Enabled=!busy && scanMode.SelectedIndex==1; pipeline.Enabled=!busy && scanMode.SelectedIndex==1;
        verify.Enabled=!busy && !deleteSource.Checked;
        stop.Enabled=busy; open.Enabled=!busy && resultDirectory!=null && Directory.Exists(resultDirectory);
        resume.Enabled=!busy && LastTask()!=null;
    }
    void OnUi(Action action) {
        if(IsDisposed || Disposing) return;
        try { BeginInvoke(action); } catch(InvalidOperationException) { }
    }
    static string Quote(string path) { return "\""+path+"\""; }
    string LastTask() {
        try {
            string pointer=Path.Combine(root,"validation","app-last-task.json");
            if(!File.Exists(pointer)) return null;
            var data=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(pointer,Encoding.UTF8));
            string path=Convert.ToString(data["task"]); return File.Exists(path)?path:null;
        } catch {return null;}
    }
    void ResumeLast() {
        string path=LastTask();
        if(path==null) {MessageBox.Show(this,"没有可恢复的任务。请先用此版本开始一个任务。","没有断点");return;}
        try {
            var task=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path,Encoding.UTF8));
            var settings=(Dictionary<string,object>)task["request"];
            files.Clear(); foreach(object value in (System.Collections.IEnumerable)settings["files"]) files.Add(Convert.ToString(value));
            RefreshQueue(); output.Text=Convert.ToString(settings["output"]);
            gap.Value=Convert.ToDecimal(settings["gap"]); pre.Value=Convert.ToDecimal(settings["pre"]);
            post.Value=Convert.ToDecimal(settings["post"]); fps.Value=Convert.ToDecimal(settings["fps"]);
            scanMode.SelectedIndex=settings.ContainsKey("scan_mode") && Convert.ToString(settings["scan_mode"])=="smart"?0:1;
            deleteSource.Checked=Convert.ToBoolean(settings["delete_source"]); verify.Checked=Convert.ToBoolean(settings["verify"]);
            StartJob(path);
        } catch(Exception error) {MessageBox.Show(this,error.Message,"不能恢复任务");}
    }
    void StartJob(string resumePath=null) {
        if(resumePath==null && files.Count==0) {MessageBox.Show(this,"请先添加至少一段录像。","还没有录像");return;}
        if(resumePath==null && files.Any(p=>!File.Exists(p))) {MessageBox.Show(this,"列表中有录像已不存在，请重新选择。","录像不存在");return;}
        string python=Path.Combine(root,cpu.Checked?".venv":".gpu-venv","Scripts","python.exe");
        if(!File.Exists(python)) {MessageBox.Show(this,"运行环境不存在，请选择 CPU 或运行 setup_gpu.ps1。","环境不可用");return;}
        try {
            string save=Path.GetFullPath(output.Text.Trim()); Directory.CreateDirectory(save);
            string requests=Path.Combine(root,"validation","app-requests"); Directory.CreateDirectory(requests);
            string request=Path.Combine(requests,Guid.NewGuid().ToString("N")+".json");
            stopRequestPath=Path.ChangeExtension(request,".stop");
            File.WriteAllText(request,json.Serialize(new {resume_task=resumePath,stop_file=stopRequestPath,files=files.ToArray(),output=save,backend=cpu.Checked?"cpu":"dml",verify=verify.Checked || deleteSource.Checked,
                delete_source=deleteSource.Checked,gap=gap.Value,pre=pre.Value,post=post.Value,fps=fps.Value,
                gpu_load=new[]{"low","balanced","fast"}[gpuLoad.SelectedIndex],pipeline=pipeline.Checked,
                scan_mode=scanMode.SelectedIndex==0?"smart":"complete"}),new UTF8Encoding(false));
            var info=new ProcessStartInfo(python,Quote(Path.Combine(root,"app_worker.py"))+" "+Quote(request)) {
                WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8
            };
            info.EnvironmentVariables["PYTHONIOENCODING"]="utf-8";
            worker=new Process {StartInfo=info}; cancelled=false; completed=false; resultDirectory=null;
            fileTotal=files.Count; fileIndex=1; fileProgress=0; progress.Value=0; log.Clear(); status.Text="启动中…";
            SetBusy(true);
            Process running=worker;
            System.Threading.Tasks.Task.Run(delegate {
                try {
                    running.Start();
                    var errors=System.Threading.Tasks.Task.Run(delegate {return running.StandardError.ReadToEnd();});
                    string line;
                    while((line=running.StandardOutput.ReadLine())!=null) {
                        string captured=line; OnUi(delegate { Receive(captured); });
                    }
                    running.WaitForExit(); string stderr=errors.Result; int exit=running.ExitCode;
                    OnUi(delegate {
                        SetBusy(false);
                        if(cancelled) {status.Text="已停止并保留断点；点击“继续上次任务”恢复。";Append(status.Text);}
                        else if(!completed) {status.Text="任务异常结束（退出码 "+exit+"）";Append(status.Text);if(stderr.Length>0) Append(stderr);}
                    });
                } catch(Exception error) {OnUi(delegate {SetBusy(false);status.Text="启动失败";Append(error.Message);});}
            });
        } catch(Exception error) {MessageBox.Show(this,error.Message,"无法开始"); SetBusy(false);}
    }
    void Receive(string line) {
        Dictionary<string,object> data;
        try {data=json.Deserialize<Dictionary<string,object>>(line);} catch {Append(line);return;}
        string type=Convert.ToString(data["type"]);
        if(data.ContainsKey("progress")) {
            fileProgress=Math.Max(fileProgress,Convert.ToInt32(data["progress"]));
            progress.Value=Math.Min(100,Math.Max(0,((fileIndex-1)*100+fileProgress)/Math.Max(1,fileTotal)));
        }
        if(type=="file") {fileIndex=Convert.ToInt32(data["index"]);fileTotal=Convert.ToInt32(data["total"]);fileProgress=0;current.Text="录像 "+fileIndex+" / "+fileTotal+"  ·  "+data["message"];}
        if(type=="run") {resultDirectory=Convert.ToString(data["directory"]); if(cancelled) WriteStopRequest();}
        if(type=="stopped") cancelled=true;
        if(data.ContainsKey("message")) {
            string message=Convert.ToString(data["message"]);
            if(type=="stage" || type=="error" || type=="fatal" || type=="result") status.Text=message;
            Append(message);
        }
        if(type=="done") {
            completed=true; progress.Value=100;
            status.Text="完成："+data["clips"]+" 段视频，"+data["review_count"]+" 个待复核，"+data["failures"]+" 个失败；回收原录像 "+(data.ContainsKey("recycled")?data["recycled"]:0)+" 份。";
            Append(status.Text); resultDirectory=Convert.ToString(data["directory"]);
        }
    }
    void Append(string message) {log.AppendText(message+Environment.NewLine);}
    void StopJob() {
        if(worker==null) return;
        cancelled=true; stop.Enabled=false; status.Text="正在停止…";
        WriteStopRequest();
    }
    void WriteStopRequest() {
        if(stopRequestPath==null) return;
        try {File.WriteAllText(stopRequestPath,"stop",new UTF8Encoding(false));}
        catch(Exception error) {Append("停止请求写入失败："+error.Message);}
    }
    void OpenResults() {
        if(resultDirectory!=null && Directory.Exists(resultDirectory)) Process.Start(new ProcessStartInfo(resultDirectory) {UseShellExecute=true});
    }
}
