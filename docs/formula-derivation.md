# 已知船端与埋设犁边界下海底缆线张力模型公式推导

## 摘要

针对铺缆船-埋设犁联合作业过程，本文建立水中悬垂段三维形态与张力分布的时域计算模型。模型输入取自船载导航、甲板放缆、水下定位、海流测量及缆材资料。

模型以船端导缆点和埋设犁入口为强制运动边界。主动悬垂长度由放缆通量、犁端铺底转移速度和端点几何可达性共同确定。

时域方程包含水中自重、Morison 阻力、节点惯性、XPBD 轴向约束及海床接触约束。初始张力由固定端自由悬链线解给出，后续张力由离散轴向约束反力确定。

TDP 接触过渡张力与犁入口边界张力分别定义；前者取接触过渡前段轴向约束反力，后者取犁入口端点相邻段轴向约束反力。

关键词：海底缆线；铺缆船；埋设犁；悬链线；XPBD；Morison 阻力；TDP；张力分布

## 1. 坐标系与基本符号

本文采用作业航迹坐标系 \(O_sx_sy_sz_s\) 作为计算坐标。\(x_s\) 沿铺缆前进方向，\(y_s\) 为作业横向，\(z_s\) 竖直向下。静水面取 \(z_s=0\)，平坦海床取 \(z_s=H\)。

船体坐标系 \(O_bx_by_bz_b\) 用于描述船载测量量。\(x_b\) 指向船艏，对应纵荡速度 \(u\)；\(y_b\) 指向右舷，对应横荡速度 \(v\)；\(z_b\) 为垂荡方向。船体艏向用于姿态变换，缆线端点速度由导缆点运动给出。

船端边界取导缆点在作业坐标中的位置 \(\mathbf r_f(t)\) 和速度 \(\mathbf v_f(t)\)。

导缆点运动由船体参考点位置、参考点速度、姿态、角速度及导缆点杆臂换算得到。SOG/COG 给出水平对地速度；姿态和角速度由电罗经、INS 或 MRU 给出。

实际边界量为导缆点和犁入口在 \(O_s\) 中的位置与速度。原始测量通常记录于局部导航坐标系 \(O_n\)，本文以 \(\mathbf R_{sn}\) 表示 \(O_n\) 到 \(O_s\) 的旋转。船载、犁载及环境数据经时间同步、杆臂修正和坐标旋转后进入张力方程。

方位角作为测量中间量。SOG/COG、艏向、海流去向角及路由切向角须先转换为 \(O_s\) 中的速度矢量或单位向量。

<!-- pagebreak -->

| 符号 | 含义 | 单位 |
| --- | --- | --- |
| \(\mathbf r_f(t)\) | 船端导缆点位置 | m |
| \(\mathbf r_p(t)\) | 埋设犁入口位置 | m |
| \(\mathbf r_i(t)\) | 第 \(i\) 个离散节点位置，\(i=0,\ldots,N\) | m |
| \(\ell_i(t)\) | 第 \(i\) 段当前长度，\(i=0,\ldots,N-1\) | m |
| \(\ell_{0,i}(t)\) | 第 \(i\) 段未拉伸长度 | m |
| \(L_s(t)\) | 主动悬垂长度 | m |
| \(L_{\min}(t)\) | 两端几何可达所需最小长度 | m |
| \(\mathbf t_i(t)\) | 第 \(i\) 段切向单位向量 | 1 |
| \(\mathbf e_b(t)\) | 犁后铺设方向单位向量 | 1 |
| \(\varepsilon_g\) | 几何可达性裕量 | 1 |
| \(D\) | 缆线等效外径 | m |
| \(W_a\) | 空气中单位长度重量 | N/m |
| \(w'\) | 水中单位长度重量 | N/m |
| \(EA\) | 轴向刚度 | N |
| \(C_t,C_n\) | 切向、法向阻力系数 | 1 |
| \(\rho_w\) | 海水密度 | kg/m³ |
| \(g\) | 重力加速度 | m/s² |
| \(H\) | 平坦海床深度 | m |
| \(\delta_c\) | 海床接触诊断容差 | m |
| \(\mu\) | 算例海床库仑摩擦系数 | 1 |
| \(\Delta t\) | 内部时间步长 | s |
| \(N_{\mathrm{XPBD}}\) | 单步约束松弛迭代次数 | 1 |
| \(\mathbf R_{sn}\) | 导航坐标到作业航迹坐标的旋转矩阵 | 1 |
| \(\mathbf R_{nb}\) | 船体坐标到导航坐标的姿态旋转矩阵 | 1 |
| \(\mathbf R_{np}\) | 犁体坐标到导航坐标的姿态旋转矩阵 | 1 |
| \(\mathbf p_0^n\) | 作业坐标原点在导航坐标中的位置 | m |
| \(\mathbf p_{\mathrm{ship}}^n\) | 船体参考点在导航坐标中的位置 | m |
| \(\mathbf p_{\mathrm{plough}}^n\) | 犁定位点在导航坐标中的位置 | m |
| \(\mathbf p_f^n,\mathbf V_f^n\) | 导缆点经杆臂修正后的导航坐标位置和速度 | m, m/s |
| \(\mathbf V_{\mathrm{rot},f}^n\) | 导缆点杆臂转动速度项 | m/s |
| \(\mathbf p_{\mathrm{in}}^n,\mathbf V_{\mathrm{in}}^n\) | 犁入口经杆臂修正后的导航坐标位置和速度 | m, m/s |
| \(S_0^n\) | 上一时刻主动悬垂段未拉伸总长 | m |
| \(\mathbf a_f^b\) | 船体坐标下导缆点杆臂 | m |
| \(\mathbf a_{\mathrm{in}}^p\) | 犁入口相对定位点的杆臂 | m |
| \(\mathcal I_t,\mathcal I_z\) | 时间同步/垂向插值算子 | 1 |
| \(\mathbf U_{c,m}^{n,\mathrm{ADCP}}(t)\) | 第 \(m\) 个 ADCP 深度单元流速 | m/s |
| \(\mathbf r_{\mathrm{route}}^s(s)\) | 作业坐标中的设计路由中心线 | m |
| \(L_{\mathrm{pay}}(t)\) | 绞车/张紧器累计放缆长度 | m |
| \(v_o(t)\) | 放缆速度 | m/s |
| \(v_b(t)\) | 悬垂段向铺底段的等效转移速度 | m/s |
| \(u_{s,i}(t)\) | 第 \(i\) 段沿缆切向滑移速度 | m/s |
| \(\xi_i(t)\) | 第 \(i\) 段归一化弧长位置 | 1 |
| \(v_\epsilon\) | 摩擦方向正则化速度 | m/s |
| \(\mathbf U_c(z,t)\) | 海流速度 | m/s |
| \(T_i(t)\) | 第 \(i\) 段张力 | N |
| \(T_f(t)\) | 船端张力 | N |
| \(T_{\mathrm{tdp}}(t)\) | TDP/接触过渡张力 | N |
| \(T_{\mathrm{in}}(t)\) | 犁入口边界张力 | N |
| \(T_{\mathrm{adj}}(t)\) | 犁端相邻段约束反力诊断量 | N |
| \(T_\epsilon\) | 张力相对误差分母下限 | N |
| \(T_{\mathrm{phys}}\) | 物理仿真时长 | s |
| \(T_{\mathrm{wall}}\) | 计算墙钟耗时 | s |
| \(\mathbf q_i(t)\) | 第 \(i\) 个节点动力学残差 | N |
| \(\mathbf R_p^{b}(t)\) | 犁端完整动态边界反力，理论残差量 | N |
| \(\mathbf F_{p}^{\mathrm{cable}\to\mathrm{plough}}\) | 缆线作用于埋设犁的结构反力 | N |
| \(\Omega_{\mathrm{cmp}}\) | 同物理定义分布对比点集合 | 1 |
| \(\mathcal M_T\) | 张力分布物理定义 | 1 |
| \(R_L\) | 工程允许最小弯曲半径 | m |

离散几何定义为

$$
\mathbf d_i=\mathbf r_{i+1}-\mathbf r_i,\qquad
\ell_i=\|\mathbf d_i\|,\qquad
\mathbf t_i=\frac{\mathbf d_i}{\ell_i}.
\tag{1}
$$

端点边界满足

$$
\mathbf r_0(t)=\mathbf r_f(t),\qquad \mathbf r_N(t)=\mathbf r_p(t).
\tag{2}
$$

## 2. 实船数据输入、端点边界与主动悬垂长度

本节采用如下假设：

1. 导缆点和犁入口均视为给定运动边界；
2. 船载、犁载、甲板和环境测量均已完成时间同步、单位统一、滤波和坐标转换；
3. 导缆点杆臂和犁入口相对定位点的杆臂均已标定；
4. 放缆长度为绞车或张紧器给出的连续时程；
5. 犁内储缆、导缆槽滑移、犁后铺底滞后和土体破坏过程由扩展模型闭合。

船端数据链如下。

| 数据来源 | 设备或资料 | 可得记录 | 入模关系 |
| --- | --- | --- | --- |
| RTK/GNSS 或 DGNSS | 船体参考点的卫星定位设备 | 船体参考点位置 \(\mathbf p_{\mathrm{ship}}^n(t)\)；位置差分可得对地速度记录 | 式 (3a)、式 (3c) |
| INS/MRU/电罗经 | 船体姿态与惯性测量设备 | 姿态矩阵 \(\mathbf R_{nb}(t)\)、角速度 \(\omega_b^b(t)\)；也可给出姿态修正后的速度记录 | 式 (3a)、式 (3b) |
| DP 或综合导航系统 | 对定位、姿态和速度进行时间同步与滤波的船载导航系统 | 计算用船体参考点位置 \(\mathbf p_{\mathrm{ship}}^n(t)\) 和速度 \(\mathbf V_{\mathrm{ship}}^n(t)\) | 式 (3a)、式 (3c) |
| 导缆点几何标定 | 导缆点相对船体参考点的船体坐标杆臂 | 导缆点杆臂 \(\mathbf a_f^b\) | 式 (3a)、式 (3b) |

上述数据换算后得到导缆点导航坐标位置 \(\mathbf p_f^n(t)\) 和速度 \(\mathbf V_f^n(t)\)，再转换为作业坐标中的 \(\mathbf r_f(t)\) 和 \(\mathbf v_f(t)\)。张力方程以预处理后的端点位置、端点速度和放缆速度为输入。

船体纵荡/横荡速度 \(u,v\) 经姿态矩阵 \(\mathbf R_{nb}\) 转为导航坐标速度。SOG/COG 给出水平对地速度；水速仪或多普勒计程仪给出的相对水速度需结合海流换算为端点对地速度。

| 输入组 | 原始记录 | 入模物理量 |
| --- | --- | --- |
| 船端导缆点 | GNSS/DGNSS/RTK 或 DP 定位融合得到的船体参考点位置，DP/INS 融合或 GNSS 差分得到的对地速度，电罗经、INS 或 MRU 给出的姿态和角速度，以及导缆点相对船体坐标的杆臂 | \(\mathbf r_f(t),\mathbf v_f(t)\) |
| 埋设犁入口 | USBL 或声学应答器位置、犁载 INS/DVL 速度、深度或高度计记录，以及犁入口相对定位点的标定杆臂 | \(\mathbf r_p(t),\mathbf v_p(t)\) |
| 放缆 | 绞车或张紧器编码器记录的累计放缆长度、编码器速度和张紧器工作状态 | \(L_{\mathrm{pay}}(t),v_o(t)\) |
| 铺设方向 | 设计路由中心线、施工导航线、已铺缆轨迹或犁后沟槽方向 | \(\mathbf e_b(t),v_b(t)\) |
| 环境 | 船载、拖曳或固定 ADCP 的分层流速，测深、潮位和姿态补偿后的海床高程 | \(\mathbf U_c(z,t),H\) |
| 缆材 | 缆型说明书、材料数据库、施工选型和施工限值记录 | \(D\)、\(W_a\)、\(w'\)、\(EA\)、\(C_t\)、\(C_n\)、\(R_L\) |

船端导缆点由船体运动和导缆点杆臂换算得到。设 \(\mathbf p_{\mathrm{ship}}^n\) 为导航坐标中的船体参考点位置，\(\mathbf V_{\mathrm{ship}}^n\) 为该参考点速度，\(\omega_b^b\) 为船体角速度向量，则

$$
\begin{aligned}
\mathbf p_f^n(t_m)
&=\mathbf p_{\mathrm{ship}}^n(t_m)
+\mathbf R_{nb}(t_m)\mathbf a_f^b,\\
\mathbf V_f^n(t_m)
&=\mathbf V_{\mathrm{ship}}^n(t_m)
+\mathbf V_{\mathrm{rot},f}^n(t_m).
\end{aligned}
\tag{3a}
$$

其中导缆点杆臂引起的转动速度项为

$$
\begin{aligned}
\mathbf V_{\mathrm{rot},f}^n(t_m)
&=\mathbf R_{nb}(t_m)\mathbf v_{\mathrm{rot},f}^b(t_m),\\
\mathbf v_{\mathrm{rot},f}^b(t_m)
&=\omega_b^b(t_m)\times\mathbf a_f^b.
\end{aligned}
\tag{3b}
$$

导缆点位置和速度转入作业航迹坐标后，有

$$
\begin{aligned}
\hat{\mathbf r}_f^s(t_m)
&=\mathbf R_{sn}\left[\mathbf p_f^n(t_m)-\mathbf p_0^n\right],\\
\hat{\mathbf v}_f^s(t_m)
&=\mathbf R_{sn}\mathbf V_f^n(t_m).
\end{aligned}
\tag{3c}
$$

埋设犁入口由声学定位点与犁入口标定偏置换算得到。设 \(\mathbf p_{\mathrm{plough}}^n\) 为 USBL 或犁载导航输出的位置，\(\mathbf a_{\mathrm{in}}^p\) 为犁入口相对定位点的杆臂，则

$$
\begin{aligned}
\mathbf p_{\mathrm{in}}^n(t_m)
&=\mathbf p_{\mathrm{plough}}^n(t_m)
+\mathbf R_{np}(t_m)\mathbf a_{\mathrm{in}}^p,\\
\mathbf V_{\mathrm{in}}^n(t_m)
&=\frac{d\mathbf p_{\mathrm{in}}^n}{dt}(t_m).
\end{aligned}
\tag{4a}
$$

式 (4a) 中的速度估计由声学定位轨迹差分、犁载 DVL/INS 速度记录和低通滤波共同确定；导数记号表示融合后的入口速度估计。

犁入口边界在作业航迹坐标中取为

$$
\begin{aligned}
\hat{\mathbf r}_p^s(t_m)
&=\mathbf R_{sn}\left[\mathbf p_{\mathrm{in}}^n(t_m)-\mathbf p_0^n\right],\\
\hat{\mathbf v}_p^s(t_m)
&=\mathbf R_{sn}\mathbf V_{\mathrm{in}}^n(t_m).
\end{aligned}
\tag{4b}
$$

当犁端姿态未提供时，\(\mathbf p_{\mathrm{plough}}^n\) 预先标定为犁入口等效点。经同步和滤波后的端点边界为

$$
\begin{aligned}
\mathbf r_q(t)&=\mathcal I_t\left[\hat{\mathbf r}_q^s(t_m)\right],\\
\mathbf v_q(t)&=\frac{d\mathbf r_q}{dt},
\qquad q\in\{f,p\}.
\end{aligned}
\tag{5}
$$

放缆速度来自绞车或张紧器编码器。以累计放缆长度 \(L_{\mathrm{pay}}\) 为原始量时，

$$
v_o(t)=\frac{dL_{\mathrm{pay}}}{dt}.
\tag{6}
$$

主动悬垂长度按一维控制体处理。假设船端物质流入速度为放缆速度 \(v_o\)，犁端物质流出速度为铺底转移速度 \(v_b\)，且悬垂段内不显式设置储缆量。犁后铺设方向取自设计路由或已铺轨迹。令 \(\mathbf r_{\mathrm{route}}^s(s)\) 为作业坐标中的设计路由中心线，则犁入口处的铺设方向单位向量为

$$
\mathbf e_b(t)=
\left.
\frac{\partial\mathbf r_{\mathrm{route}}^s/\partial s}
{\left\|\partial\mathbf r_{\mathrm{route}}^s/\partial s\right\|}
\right|_{s=s_p(t)}.
\tag{7a}
$$

令 \(\mathbf v_{p,h}=(v_{p,x},v_{p,y},0)\) 为犁入口水平速度，则悬垂段向铺底段的等效转移速度取

$$
v_b(t)=\max\left[0,\mathbf v_{p,h}(t)\cdot \mathbf e_b(t)\right].
\tag{7b}
$$

式 (3a)--(7b) 给出端点运动、放缆通量和铺底转移通量。主动悬垂长度满足

$$
\begin{aligned}
\frac{dL_s}{dt}&=v_o(t)-v_b(t),\\
L_s(t)&\ge L_{\min}(t),\\
L_{\min}(t)&=(1+\varepsilon_g)\|\mathbf r_p(t)-\mathbf r_f(t)\|.
\end{aligned}
\tag{7c}
$$

离散时刻 \(t^n\to t^{n+1}=t^n+\Delta t\) 写作

$$
\begin{aligned}
\widetilde L_s^{\,n+1}
&=L_s^n+\int_{t^n}^{t^{n+1}}
\left[v_o(\tau)-v_b(\tau)\right]d\tau,\\
L_s^{n+1}
&=\max\left[L_{\min}^{n+1},\widetilde L_s^{\,n+1}\right],
\end{aligned}
\tag{7d}
$$

其中 \(\varepsilon_g\) 为几何闭合裕量。由式 (7a)--(7d) 可知，\(v_o>v_b\) 时悬垂段增长，\(v_o<v_b\) 时悬垂段缩短。本文取

$$
\varepsilon_g=10^{-3},
\tag{7e}
$$

该量用于避免端点距离与不可伸长约束发生不可达冲突。

第 12 节算例采用直线路由，\(\mathbf v_{p,h}\) 与 \(\mathbf e_b\) 共线。该算例中的主动悬垂长度初值取 3% 余长，

$$
L_{s,0}^{\mathrm{lin}}
=1.03\|\mathbf r_p(0)-\mathbf r_f(0)\|,
\tag{7f}
$$

后续时刻取犁端平面速度模长作为铺底转移速度，

$$
v_b^{\mathrm{lin}}
=\sqrt{v_{p,x}^2+v_{p,y}^2},
\tag{7g}
$$

并按

$$
\begin{aligned}
L_s^{\mathrm{lin},n+1}
=\max\bigl[
&1.001\|\mathbf r_p^{\,n+1}-\mathbf r_f^{\,n+1}\|,\\
&L_s^{\mathrm{lin},n}
+(v_o^n-v_b^{\mathrm{lin},n})\Delta t
\bigr].
\end{aligned}
\tag{7h}
$$

因此，式 (7f)--(7h) 为第 12 节直线路由算例的离散闭合。存在曲线路由或明显横漂时，应采用式 (7b) 的路由投影定义。

主动长度变化后的未拉伸段长按上一时刻段长比例缩放：

$$
\begin{aligned}
S_0^n&=\sum_{j=0}^{N-1}{\ell_{0,j}^{n}},\\
\ell_{0,i}^{n+1}
&=\frac{\ell_{0,i}^{n}}{S_0^n}L_s^{n+1},\\
i&=0,\ldots,N-1.
\end{aligned}
\tag{8a}
$$

若上一时刻总长度退化为零，则采用均分初始化：

$$
\ell_{0,i}^{n+1}=\frac{L_s^{n+1}}{N}.
\tag{8b}
$$

未拉伸段长按主动悬垂长度归一化：

$$
\sum_{i=0}^{N-1}{\ell_{0,i}^{n+1}}=L_s^{n+1}.
\tag{8c}
$$

## 3. 材料质量、海流与 Morison 阻力

本节采用如下假设：

1. 缆线等效为细长圆柱，截面参数沿线恒定；
2. 海水密度、重力加速度和阻力系数在给定算例内取常数；
3. 海流剖面由实测或给定剖面插值得到；
4. 水动力采用切向、法向分解的 Morison 阻力；
5. 海床接触摩擦按第 7 节的接触模型处理。

缆材参数来自缆型资料、材料数据库和施工选型记录。空气中单位长度重量 \(W_a\) 用于等效干质量，水中单位长度重量 \(w'\) 直接用于水中自重；外径 \(D\)、轴向刚度 \(EA\) 和阻力系数 \(C_t,C_n\) 分别进入动力质量、轴向约束和水动力项。接触摩擦采用算例给定的海床库仑摩擦系数 \(\mu\)。

结构质量与附加质量合并为单位长度动力质量

$$
m'=\frac{W_a}{g}
+\rho_w\frac{\pi D^2}{4},
\tag{9}
$$

式 (9) 的第二项为单位长度圆柱排水体附加质量。节点 \(i\) 的控制长度为

$$
\Delta s_i=\frac12\ell_{0,i-1}+\frac12\ell_{0,i},
\tag{10}
$$

端点处只取相邻半段。节点质量为 \(m_i=m'\Delta s_i\)。

海流输入来自 ADCP 或等效流速剖面。设 \(\mathbf U_{c,m}^{n,\mathrm{ADCP}}(t)\) 为第 \(m\) 个深度单元在导航坐标中的水体速度，\(\mathcal I_z\) 为按实测深度单元建立的垂向插值算子，则进入 Morison 阻力的作业坐标海流为

$$
\mathbf U_c(z,t)
=\mathbf R_{sn}\mathcal I_z
\left[\mathbf U_{c,m}^{n,\mathrm{ADCP}}(t)\right](z).
\tag{11}
$$

海床深度 \(H\) 来自测深、潮位和船体姿态补偿后的施工面高程。平坦海床情形取常数 \(H\)；非平坦海床应将后续接触约束中的 \(H\) 替换为局部海床函数 \(H(x_s,y_s)\)。

一般路由下，第 \(i\) 段中点材料速度采用 ALE 型滑移表达。节点平均速度及其法向几何分量定义为

$$
\bar{\mathbf v}_i=\frac{\mathbf v_i+\mathbf v_{i+1}}{2},\qquad
\bar{\mathbf v}_{i}^{\perp}
=\bar{\mathbf v}_i-\left(\bar{\mathbf v}_i\cdot\mathbf t_i\right)\mathbf t_i.
\tag{12a}
$$

沿缆滑移速度场与式 (7a)--(7c) 的入口和出口通量一致。令

$$
\begin{aligned}
\xi_i(t)&=
\frac{\sum_{j=0}^{i-1}{\ell_{0,j}(t)}+\frac12\ell_{0,i}(t)}
{L_s(t)},\\
0&\le \xi_i\le 1,
\end{aligned}
\tag{12b}
$$

则采用线性通量插值

$$
\begin{aligned}
u_{s,i}(t)
&=\left[1-\xi_i(t)\right]v_o(t)\\
&\quad+\xi_i(t)v_b(t).
\end{aligned}
\tag{12c}
$$

于是第 \(i\) 段参与 Morison 阻力计算的材料速度为

$$
\mathbf u_{m,i}
=\bar{\mathbf v}_{i}^{\perp}+u_{s,i}\mathbf t_i .
\tag{12d}
$$

当船端与犁端材料通量相等时，式 (12c) 退化为均匀滑移速度

$$
\mathbf u_{m,i}^{\mathrm{lin}}
=\bar{\mathbf v}_{i}^{\perp}+v_o\mathbf t_i .
\tag{12e}
$$

式 (12e) 仅是 \(v_o=v_b\) 时式 (12c) 的特例。非等量通量工况采用式 (12c)，以保证船端放缆速度与犁端铺底转移速度分别构成材料滑移速度场的两端边界。

式 (12a)--(12d) 将节点法向几何运动与沿缆材料滑移分离，避免切向速度重复计入。

由于 \(\xi_i\) 位于段中心，\(u_{s,i}\) 以线性插值近似连接船端放缆通量与犁端铺底转移通量。若引入犁内滑移或沿线重网格通量，应以局部材料通量方程替代式 (12c)。

缆材相对水体速度定义为

$$
\mathbf u_{r,i}=\mathbf u_{m,i}-\mathbf U_c(z_i).
\tag{13}
$$

切向与法向分量为

$$
u_{t,i}=\mathbf u_{r,i}\cdot\mathbf t_i,\qquad
\mathbf u_{n,i}=\mathbf u_{r,i}-u_{t,i}\mathbf t_i.
\tag{14}
$$

式 (13) 表示缆相对水运动，阻力取相对速度反向。第 \(i\) 段 Morison 阻力写作

$$
\begin{aligned}
\mathbf F_{D,i}&=\mathbf F_{D,i}^{t}+\mathbf F_{D,i}^{n},\\
\mathbf F_{D,i}^{t}&=-\frac12\pi\rho_w C_tD\ell_i u_{t,i}|u_{t,i}|\mathbf t_i,\\
U_{n,i}&=(\mathbf u_{n,i}\cdot\mathbf u_{n,i})^{1/2},\\
\mathbf F_{D,i}^{n}&=-\frac12\rho_w C_nD\ell_iU_{n,i}\mathbf u_{n,i}.
\end{aligned}
\tag{15}
$$

水中自重为

$$
\mathbf W_i=(0,\ 0,\ w'\ell_{0,i}).
\tag{16}
$$

## 4. 首帧固定端悬链线反力

本节初值采用如下假设：

1. 初始水中悬垂段处于自由悬垂状态；
2. 两端位置固定，主动悬垂长度已知；
3. 初始静力载荷取水中自重；
4. 缆线不可压缩，且初始长度满足两端几何可达条件。

在上述假设下，固定端自由悬链线给出首帧张力初值。令水平跨距

$$
X=\sqrt{(x_p-x_f)^2+(y_p-y_f)^2},
\tag{17}
$$

竖向落差

$$
Z=z_p-z_f,
\tag{18}
$$

初始主动悬垂长度为 \(L_s^0\)。若 \(L_s^0>\sqrt{X^2+Z^2}\) 且 \(|Z|<L_s^0\)，定义约化长度

$$
L_r=\sqrt{(L_s^0)^2-Z^2}.
\tag{19}
$$

悬链线参数 \(a\) 由下式唯一确定：

$$
L_r=2a\sinh\left(\frac{X}{2a}\right).
\tag{20}
$$

定义

$$
\eta=\operatorname{artanh}\left(\frac{Z}{L_s^0}\right),\qquad
\xi_f=\eta+\frac{X}{2a},\qquad
\xi_p=\eta-\frac{X}{2a}.
\tag{21}
$$

水平张力为

$$
T_h=w'a.
\tag{22}
$$

船端与犁端静态张力为

$$
T_f^0=T_h\cosh\xi_f,\qquad
T_p^0=T_h\cosh\xi_p.
\tag{23}
$$

第 \(i\) 段初始张力种子取

$$
T_i^0
=T_h\cosh\left[
\xi_f+\frac{i}{N-1}(\xi_p-\xi_f)
\right],
\qquad i=0,\ldots,N-1.
\tag{24}
$$

自由悬链线初态需满足 \(z_i\le H\)。以弧长分数 \(\alpha_i=i/N\) 写作

$$
\xi_i=\operatorname{arsinh}\left(\sinh\xi_f-\alpha_i\frac{L_s^0}{a}\right),
\tag{25}
$$

对应深度为

$$
z_i=z_f+a\left(\cosh\xi_f-\cosh\xi_i\right).
\tag{26}
$$

若存在 \(z_i>H\)，该初态应采用含海床接触的静力模型。

## 5. 节点动力学预测

本节采用集中质量离散。缆线由 \(N\) 个线段和 \(N+1\) 个节点组成；段载荷按半段权重分配至相邻节点；端点由式 (2) 的强制边界给定，内节点按半隐式格式预测。

记第 \(i\) 个节点总外力为

$$
\mathbf F_i^{\,n}
=\sum_{j\in\mathcal S(i)}{\omega_{ij}\left(\mathbf W_j+\mathbf F_{D,j}\right)}
+\mathbf F_{\mu,i},
\tag{27}
$$

其中 \(\mathcal S(i)\) 为节点 \(i\) 的相邻缆段集合，\(\omega_{ij}\) 为半段分配权重，\(\mathbf F_{\mu,i}\) 为接触摩擦力。半隐式预测为

$$
\begin{aligned}
\mathbf v_i^\ast&=\mathbf v_i^n+\Delta t\,m_i^{-1}\mathbf F_i^{\,n},\\
\mathbf r_i^\ast&=\mathbf r_i^n+\Delta t\,\mathbf v_i^\ast.
\end{aligned}
\tag{28}
$$

端点满足强制边界

$$
\begin{aligned}
\mathbf r_0^\ast&=\mathbf r_f^{n+1},&
\mathbf r_N^\ast&=\mathbf r_p^{n+1},\\
\mathbf v_0^\ast&=\dot{\mathbf r}_f^{\,n+1},&
\mathbf v_N^\ast&=\dot{\mathbf r}_p^{\,n+1}.
\end{aligned}
\tag{29}
$$

## 6. XPBD 轴向约束

本节采用如下约束假设：

1. 缆线可承拉、不可承压；
2. 轴向伸长由等效刚度 \(EA\) 控制；
3. 船端与犁端为强制运动边界，其逆质量取零；
4. 单个时间步内长度乘子从零开始累积，乘子表示该步约束反力。

轴向长度约束为

$$
C_i(\mathbf r)=\|\mathbf r_{i+1}-\mathbf r_i\|-\ell_{0,i}\le 0.
\tag{30}
$$

由于缆线可承拉不可承压，当 \(C_i>0\) 时产生正张力。令逆质量为 \(w_i=m_i^{-1}\)，强制端点取

$$
w_0=w_N=0.
\tag{31a}
$$

长度约束柔度写作

$$
\alpha_i=\frac{\ell_{0,i}}{EA\,\Delta t^2}.
\tag{31b}
$$

本模型的 \(\lambda_i\) 为单个时间步内初始化为零、并在约束松弛中累积的正拉力乘子，单位为 \(\mathrm{N\,s^2}\)。第 \(k\) 次约束松弛中的乘子增量为

$$
\begin{aligned}
\delta\lambda_i
&=\frac{C_i-\alpha_i\lambda_i}{w_i+w_{i+1}+\alpha_i},\\
\lambda_i^+&=\max(0,\lambda_i+\delta\lambda_i).
\end{aligned}
\tag{32}
$$

设

$$
\begin{aligned}
\mathbf n_i&=\frac{\mathbf r_{i+1}-\mathbf r_i}{\|\mathbf r_{i+1}-\mathbf r_i\|},\\
\delta\lambda_i^\ast&=\lambda_i^+-\lambda_i,
\end{aligned}
\tag{33}
$$

则位置修正为

$$
\begin{aligned}
\mathbf r_i^+&=\mathbf r_i+w_i\delta\lambda_i^\ast\mathbf n_i,\\
\mathbf r_{i+1}^+&=\mathbf r_{i+1}-w_{i+1}\delta\lambda_i^\ast\mathbf n_i.
\end{aligned}
\tag{34}
$$

数值模型采用

$$
N_{\mathrm{XPBD}}=40
\tag{35}
$$

次长度、接触与弯曲约束松弛，以兼顾不可伸长几何残差和实时计算速度。

由 XPBD 长度乘子得到第 \(i\) 段轴向约束反力近似

$$
T_i^{\lambda}
=\max\left(0,\frac{\lambda_i}{\Delta t^2}\right).
\tag{36}
$$

该量是离散约束反力意义下的数值张力定义；连续介质截面应力需由相应本构关系解释。可视缆段张力分布与船端张力采用

$$
T_i=T_i^{\lambda},\qquad
T_f=T_0^{\lambda}.
\tag{37}
$$

式 (36)--(37) 为本文张力分布的主定义。若长度约束反力退化，则第 8 节的载荷递推量作为诊断量使用，连续介质截面应力仍以式 (36)--(37) 的约束反力定义为准。

节点张力可由相邻段平均得到：

$$
T_i^{\mathrm{node}}
=\frac{1}{|\mathcal A_i|}
\sum_{j\in\mathcal A_i}{T_j},
\tag{38}
$$

其中 \(\mathcal A_i\) 为与节点 \(i\) 相邻的缆段集合。

## 7. 海床接触、摩擦与 TDP

本节采用如下接触假设：

1. 海床为刚性不可穿透边界；
2. 平坦海床深度为常数 \(H\)；
3. 接触作用于内节点，船端和犁端由强制边界给定；
4. 海床切向作用采用库仑摩擦模型；
5. 接触摩擦方向由接触处材料水平速度确定。

平坦海床不可穿透条件为

$$
g_i(\mathbf r)=z_i-H\le 0.
\tag{39}
$$

若预测或约束松弛后 \(z_i>H\)，则节点投影到海床：

$$
z_i^+=H,\qquad v_{z,i}^+=\min(v_{z,i},0).
\tag{40}
$$

接触乘子可写为

$$
\lambda_i^c\leftarrow\lambda_i^c+\frac{z_i-H}{w_i},
\qquad z_i>H,
\tag{41}
$$

对应法向反力为

$$
R_i^c=\max\left(0,\frac{\lambda_i^c}{\Delta t^2}\right).
\tag{42}
$$

式 (41) 和式 (42) 用于内节点接触约束；船端和犁端由强制运动边界给定。由于 \(z\) 轴向下，接触反力向量为

$$
\mathbf R_i^c=(0,0,-R_i^c),
\qquad i=1,\ldots,N-1.
\tag{42b}
$$

端点取 \(\mathbf R_0^c=\mathbf R_N^c=\mathbf 0\)。

库仑摩擦沿接触节点水平材料速度反向。离散接触步采用节点速度叠加放缆切向速度形成摩擦速度。定义

$$
\begin{aligned}
\mathbf u_{c,i}
&=\dot{\mathbf r}_i+v_o\mathbf t_i,\\
\mathbf v_{h,i}^{c}
&=\mathbf u_{c,i}-(\mathbf u_{c,i}\cdot\mathbf e_z)\mathbf e_z,\\
\mathbf e_z&=(0,0,1),
\end{aligned}
\tag{43a}
$$

并以 \(v_\epsilon\) 避免零速奇异，则

$$
\mathbf F_{\mu,i}
=-\mu R_i^c
\frac{\mathbf v_{h,i}^{c}}
{\sqrt{\mathbf v_{h,i}^{c}\cdot\mathbf v_{h,i}^{c}+v_\epsilon^2}}.
\tag{43b}
$$

端点摩擦取 \(\mathbf F_{\mu,0}=\mathbf F_{\mu,N}=\mathbf 0\)。

TDP 定义为从船端向犁端方向第一个接触海床的位置。若节点 \(j\) 为首次接触节点，则接触过渡前自由悬垂段的末端段索引为

$$
i_{\mathrm{tdp}}=\max(0,j-1).
\tag{44}
$$

## 8. TDP 张力与犁入口边界张力

本节采用如下假设：

1. 埋设犁作为给定运动边界处理；
2. 犁内滑移、导缆槽摩擦、犁土反力和土体破坏过程由扩展模型闭合；
3. TDP 接触过渡张力与犁入口边界张力分别定义；
4. 完整犁端结构反力作为理论残差量给出。

由于埋设犁被视为给定运动边界，犁端相邻段的约束反力可包含贴底尾段被端点强制闭合产生的局部反力。本文分别定义 TDP 接触过渡张力和犁入口边界张力。

令 \(i_{\mathrm{tdp}}\) 为接触过渡前自由悬垂段末端段索引，则 TDP 接触过渡张力为

$$
T_{\mathrm{tdp}}=T_{i_{\mathrm{tdp}}}^{\lambda}.
\tag{45}
$$

犁入口边界张力取犁入口端点相邻段约束反力：

$$
T_{\mathrm{in}}=T_{N-1}^{\lambda}.
\tag{45b}
$$

犁端相邻段诊断量写为

$$
T_{\mathrm{adj}}=T_{N-1}^{\lambda}.
\tag{45c}
$$

对内节点 \(i=1,\ldots,N-1\)，完整动态节点控制体平衡可写作

$$
\begin{aligned}
m_i\mathbf a_i
&=T_i\mathbf t_i-T_{i-1}\mathbf t_{i-1}\\
&\quad+\sum_{j\in\mathcal S(i)}{\omega_{ij}\left(\mathbf W_j+\mathbf F_{D,j}\right)}\\
&\quad+\mathbf F_{\mu,i}+\mathbf R_i^c .
\end{aligned}
\tag{46a}
$$

其中 \(\mathcal S(i)\) 为节点 \(i\) 的相邻缆段集合，\(\omega_{ij}\) 为半段分配权重，\(\mathbf R_i^c\) 为接触法向反力。对应的节点动力学残差为

$$
\begin{aligned}
\mathbf q_i
&=m_i\mathbf a_i-\left(T_i\mathbf t_i-T_{i-1}\mathbf t_{i-1}\right)\\
&\quad-\sum_{j\in\mathcal S(i)}{\omega_{ij}\left(\mathbf W_j+\mathbf F_{D,j}\right)}\\
&\quad-\mathbf F_{\mu,i}-\mathbf R_i^c .
\end{aligned}
\tag{46b}
$$

当残差收敛且边界反力需要作为输出时，犁端节点 \(N\) 的边界反力可由

$$
\begin{aligned}
\mathbf R_p^{b}
&=m_N\mathbf a_N+T_{N-1}\mathbf t_{N-1}\\
&\quad-\sum_{j\in\mathcal S(N)}{\omega_{Nj}\left(\mathbf W_j+\mathbf F_{D,j}\right)} .
\end{aligned}
\tag{46c}
$$

其中端点接触与端点摩擦按式 (42b) 和式 (43b) 的约定为零。式 (46c) 中 \(\mathbf R_p^{b}\) 表示外部强制边界对缆线的反力。缆线作用于埋设犁的结构反力为

$$
\mathbf F_{p}^{\mathrm{cable}\to\mathrm{plough}}=-\mathbf R_p^{b}.
\tag{46d}
$$

本文输出的 TDP 张力采用式 (45) 的接触过渡段约束张力口径；犁入口边界张力采用式 (45b) 的端点相邻段约束张力口径。式 (46c) 表示完整动态犁端结构反力。

为保留准静态审计量，可另定义自由悬垂段载荷递推诊断。诊断递推只在 \(i=0,\ldots,i_{\mathrm{tdp}}\) 的自由悬垂段上定义。

记 \(T_i^r\) 为第 \(i\) 段靠船端一侧截面的递推张力，\(T_{i+1}^r\) 为同段靠 TDP 接触过渡一侧截面的递推张力。末端种子为

$$
T_{i_{\mathrm{tdp}}+1}^{r}=0.
\tag{47}
$$

令自由悬垂段第 \(i\) 段的准静态切向载荷为

$$
Q_i^r=\left(\mathbf W_i+\mathbf F_{D,i}\right)\cdot\mathbf t_i .
\tag{48a}
$$

相对于完整节点控制体平衡，该诊断载荷省略项可记为

$$
\Delta Q_i^r
=\left(-m_i\mathbf a_i+\mathbf F_{\mu,i}+\mathbf R_i^c\right)\cdot\mathbf t_i
+Q_i^{\mathrm{curv}},
\tag{48b}
$$

其中 \(Q_i^{\mathrm{curv}}\) 表示相邻段切向方向改变导致的张力方向耦合项。载荷递推诊断采用 \(Q_i^r\)，省略 \(\Delta Q_i^r\)。

自 TDP 接触过渡方向向船端递推：

$$
\begin{aligned}
T_i^{r}
&=\max\left[0,\ T_{i+1}^{r}+Q_i^r\right],\\
i&=i_{\mathrm{tdp}},i_{\mathrm{tdp}}-1,\ldots,0.
\end{aligned}
\tag{48c}
$$

若存在 TDP 接触过渡，则递推诊断量为

$$
T_{\mathrm{tdp}}^{r}=T_{i_{\mathrm{tdp}}}^{r}.
\tag{49}
$$

若全段未接触海床，则

$$
T_{\mathrm{tdp}}=T_{\mathrm{in}}=T_{\mathrm{adj}},\qquad
T_{\mathrm{tdp}}^{r}=T_{\mathrm{adj}}.
\tag{50}
$$

由式 (45)--(50) 可见，\(T_{\mathrm{tdp}}\) 表征自由悬垂段与海床接触过渡处的轴向约束反力；\(T_{\mathrm{in}}\) 表征犁入口端点相邻离散段的轴向约束反力。

在无贴底尾段强制闭合、接触定义一致且惯性和摩擦影响可忽略时，二者可近似相等。

## 9. 最小弯曲半径

令相邻两段切向夹角为

$$
\begin{aligned}
\phi_i&=\arccos\left(\mathbf t_{i-1}\cdot\mathbf t_i\right),\\
i&=1,\ldots,N-1.
\end{aligned}
\tag{51}
$$

离散曲率半径估计为

$$
R_i=\frac{\frac12(\ell_{i-1}+\ell_i)}{\phi_i},
\qquad \phi_i>0.
\tag{52}
$$

最小弯曲半径输出为

$$
R_{\min}=\min_i R_i.
\tag{53}
$$

记 \(R_L\) 为工程允许最小弯曲半径，弯曲半径裕度为

$$
M_R=R_{\min}-R_L.
\tag{54}
$$

## 10. 输出物理量

本节输出采用如下范围：

1. 三维形态以离散节点坐标表示；
2. 段张力主定义为 XPBD 轴向约束反力；
3. TDP 张力采用第 8 节的接触过渡前段约束张力；
4. 犁入口边界张力采用犁端相邻段约束反力，完整犁端结构反力保留为理论比较量。

在任意物理输出时刻 \(t_k\)，模型输出下列量：

| 输出量 | 数学定义 | 物理含义 |
| --- | --- | --- |
| 三维节点 | \(\{\mathbf r_i(t_k)\}_{i=0}^{N}\) | 水中悬垂段与贴底尾段形态 |
| 段张力分布 | \(\{T_i^{\lambda}(t_k)\}_{i=0}^{N-1}\) | 离散缆段轴向约束反力 |
| 船端张力 | \(T_f(t_k)=T_0^{\lambda}(t_k)\) | 导缆点相邻段轴向约束反力 |
| TDP 张力 | \(T_{\mathrm{tdp}}(t_k)=T_{i_{\mathrm{tdp}}}^{\lambda}(t_k)\) | 接触过渡前自由悬垂段末段约束张力 |
| 犁入口边界张力 | \(T_{\mathrm{in}}(t_k)=T_{N-1}^{\lambda}(t_k)\) | 犁入口端点相邻段约束反力 |
| 犁端相邻段反力 | \(T_{\mathrm{adj}}(t_k)=T_{N-1}^{\lambda}(t_k)\) | 末段约束反力诊断量 |
| 海床接触诊断 | \(\{i\mid z_i(t_k)\ge H-\delta_c\}\) | 由节点深度和接触容差后处理得到的接触节点集合 |
| 弯曲半径 | \(R_{\min}(t_k)\) | 几何弯曲风险指标 |

## 11. 外部数值参照与误差量

本节采用如下比较假设：

1. 外部静力或动力数值工具作为同物理定义参照；
2. 标量误差在物理输出时刻、端点位置、主动悬垂长度、材料参数、海床条件、海流条件和输出物理量一致时定义；
3. 动力参照还需具有相同动态历史窗口，或具有明确等价的初始化状态；
4. 犁端完整结构反力与入犁前切向张力分别比较。

记输入集合为 \(\mathcal I\)，动态历史窗口为 \(\mathcal H_k=[t_a,t_k]\)，初始化状态为 \(\mathcal S_0\)，输出物理量为 \(\mathcal M\)。数值误差仅在下列条件成立时定义：

$$
\begin{aligned}
\mathfrak C_{\mathcal M}(t_k)=
1
\Longleftrightarrow\quad
&\mathcal I=\mathcal I^{\mathrm{ref}},\\
&t_k=t_k^{\mathrm{ref}},\\
&\left(\mathcal H_k=\mathcal H_k^{\mathrm{ref}}\right)
\vee
\left(\mathcal S_0=\mathcal S_0^{\mathrm{ref}}\right),\\
&\mathcal M=\mathcal M^{\mathrm{ref}}.
\end{aligned}
\tag{55a}
$$

令 \(\mathcal S(t_k)\) 表示模型状态，常用标量物理量算子为

$$
\begin{aligned}
\mathcal M_f[\mathcal S]&=T_f,\\
\mathcal M_{\mathrm{tdp}}[\mathcal S]&=T_{\mathrm{tdp}},\\
\mathcal M_{\mathrm{in}}[\mathcal S]&=T_{\mathrm{in}},\\
\mathcal M_{\mathrm{adj}}[\mathcal S]&=T_{\mathrm{adj}},\\
\mathcal M_p^b[\mathcal S]&=\max\left(0,\tau_p^b\right),\\
\tau_p^b&=-\mathbf F_p^{\mathrm{cable}\to\mathrm{plough}}\cdot\mathbf t_{N-1}.
\end{aligned}
\tag{55b}
$$

其中 \(\mathcal M_p^b\) 为完整犁端结构反力沿入犁缆线方向的正拉力投影。

本文可直接比较的犁侧量为 \(T_{\mathrm{tdp}}\)、\(T_{\mathrm{in}}\) 与 \(T_{\mathrm{adj}}\)。式 (55b) 中的 \(\mathbf R_p^{b}\) 和 \(\mathcal M_p^b\) 用于定义完整犁端结构反力的理论比较量。

完整三维结构反力采用向量范数或三分量误差。取 \(T_\epsilon=1\ \mathrm N\) 作为小张力分母下限，则同物理定义标量相对误差为

$$
\begin{aligned}
A_{\mathcal M}(t_k)
&=\mathcal M[\mathcal S](t_k),\\
A_{\mathcal M}^{\mathrm{ref}}(t_k)
&=\mathcal M[\mathcal S^{\mathrm{ref}}](t_k),\\
\Delta_{\mathcal M}(t_k)
&=\left|A_{\mathcal M}(t_k)-A_{\mathcal M}^{\mathrm{ref}}(t_k)\right|,\\
D_{\mathcal M}(t_k)
&=\max\left(\left|A_{\mathcal M}^{\mathrm{ref}}(t_k)\right|,T_\epsilon\right),\\
e_{\mathcal M}(t_k)
&=\frac{\Delta_{\mathcal M}(t_k)}{D_{\mathcal M}(t_k)}.
\end{aligned}
\tag{55c}
$$

式 (55c) 在 \(\mathfrak C_{\mathcal M}(t_k)\) 成立时使用。

张力分布误差在直接同物理定义的离散点集合 \(\Omega_{\mathrm{cmp}}\) 上定义，可写为无量纲相对均方根误差

\(\mathcal M_T\) 表示张力分布的物理定义，例如段轴向约束反力、节点张力或连续线张力插值。

$$
\begin{aligned}
\mathfrak C_T(t_k)=
1
\Longleftrightarrow\quad
&\mathcal I=\mathcal I^{\mathrm{ref}},\\
&t_k=t_k^{\mathrm{ref}},\\
&\left(\mathcal H_k=\mathcal H_k^{\mathrm{ref}}\right)
\vee
\left(\mathcal S_0=\mathcal S_0^{\mathrm{ref}}\right),\\
&\mathcal M_T=\mathcal M_T^{\mathrm{ref}},\\
&\Omega_{\mathrm{cmp}}\ne\emptyset.
\end{aligned}
\tag{56a}
$$

先定义归一化点误差

$$
\begin{aligned}
T_m&=T(\sigma_m,t_k),\\
T_m^{\mathrm{ref}}&=T^{\mathrm{ref}}(\sigma_m,t_k),\\
\Delta_T(\sigma_m,t_k)
&=T_m-T_m^{\mathrm{ref}},\\
D_T(\sigma_m,t_k)
&=\max\left(|T_m^{\mathrm{ref}}|,\ T_\epsilon\right),\\
\delta_T(\sigma_m,t_k)
&=\frac{\Delta_T(\sigma_m,t_k)}{D_T(\sigma_m,t_k)}.
\end{aligned}
\tag{56b}
$$

则张力分布误差为

$$
e_T(t_k)=\sqrt{\operatorname{mean}_{m\in\Omega_{\mathrm{cmp}}}\left[\delta_T^2(\sigma_m,t_k)\right]}.
\tag{56c}
$$

式 (56b) 和式 (56c) 在 \(\mathfrak C_T(t_k)\) 成立时使用。这里 \(\sigma_m\in[0,1]\) 为归一化弧长坐标。

接触模型诊断点或犁端力定义存在差异的点从 \(\Omega_{\mathrm{cmp}}\) 中剔除。

计算速度指标定义为

$$
\mathcal R_t=\frac{T_{\mathrm{phys}}}{T_{\mathrm{wall}}},
\tag{57}
$$

\(\mathcal R_t>1\) 表示快于实时。

## 12. 同输入验证算例摘要

本节采用如下验证条件：

1. 算例为直线路由、平坦海床和均匀海流；
2. 船端、犁端和放缆速度均为常值；
3. MoorPy 作为同端点、同长度、同材料的无流静力参照；
4. MoorDyn endpoint-history 作为动态历史参照；本节静力误差闭合采用 MoorPy 与闭式悬链线。

基准工况为直线路由 6 min 铺设过程。其物理窗口为 \(0\sim360\ \mathrm s\)，输出时刻包括 \(t=0\ \mathrm s\) 与 \(t=360\ \mathrm s\)，输出帧数为 361。

本节采用两个诊断数据集。数据集 A 为上述基准工况的 360 s、361 帧输出，以及与末帧端点、主动悬垂长度和材料参数一致的 MoorPy 无流静力参照；数据集 B 为首帧固定端悬链线与 MoorPy 静力审计。成熟工具动态等效需另行进行同历史窗口验证。

闭式悬链线与 MoorPy 用于同端点、同长度和同材料的静力参照；本节 MoorPy 静力参照采用无流静力设定。MoorDyn endpoint-history 属于动态历史参照；式 (58)--(63) 的静力误差闭合采用闭式悬链线与 MoorPy。

| 输入类别 | 数值 |
| --- | --- |
| 水深与海床 | \(H=80.0\ \mathrm m\)，平坦海床 \(z=H\) |
| 材料参数 | \(D=0.0264\ \mathrm m\)，\(W_a=16.09\ \mathrm{N/m}\)，\(w'=10.59\ \mathrm{N/m}\)，\(EA=1.0\times10^9\ \mathrm N\)，\(C_t=0.01\)，\(C_n=2.12\) |
| 流体常数 | \(\rho_w=1025\ \mathrm{kg/m^3}\)，\(g=9.8\ \mathrm{m/s^2}\) |
| 初始端点 | \(\mathbf r_f(0)=(0,0,0)\ \mathrm m\)，\(\mathbf r_p(0)=(-55,0,80)\ \mathrm m\) |
| 端点与绞车等效输入 | 经式 (3a)--(6) 处理后的船端 \(\mathbf v_f=(0.80,0,0)\ \mathrm{m/s}\)，犁入口 \(\mathbf v_p=(0.75,0,0)\ \mathrm{m/s}\)，放缆 \(v_o=0.88\ \mathrm{m/s}\)，均为常值 |
| ADCP 等效海流 | \(\mathbf U_c=(0,0.35,0)\ \mathrm{m/s}\)，深度均匀 |
| 离散与时间 | \(N=24\)，输出帧数 361，内部时间步 \(0.05\ \mathrm s\)，\(N_{\mathrm{XPBD}}=40\) |
| 接触与摩擦 | 平坦海床硬投影，接触容差 \(1.0\times10^{-3}\ \mathrm m\)，库仑摩擦系数 \(\mu=0.6\) |
| TDP 输入名义值 | \(200\ \mathrm N\)，作为工况标识；已知犁轨迹分支采用给定犁端运动边界 |
| 外部参照条件 | MoorPy：同端点、同长度、同材料的无流静力参照；MoorDyn endpoint-history：动态历史参照 |

首帧固定端悬链线反力与同输入闭式解一致：

$$
\begin{aligned}
T_f^0&=1274.88499841\ \mathrm N,\\
T_p^0&=427.68499841\ \mathrm N.
\end{aligned}
\tag{58}
$$

同一首帧与 MoorPy 静力值的差异为

$$
\begin{aligned}
\Delta T_f^0&=0.164155739\ \mathrm N,\\
\Delta T_p^0&=0.048721526\ \mathrm N.
\end{aligned}
\tag{59}
$$

在 \(N_{\mathrm{XPBD}}=40\) 时，末帧几何长度残差约为

$$
\Delta L=0.040678773\ \mathrm m.
\tag{60}
$$

该基准 \(T_{\mathrm{phys}}=360\ \mathrm s\)、361 个输出帧的计算耗时约为

$$
\begin{aligned}
T_{\mathrm{wall}}&=8.0197926\ \mathrm s,\\
\mathcal R_t&=44.8889414.
\end{aligned}
\tag{61}
$$

末帧 MoorPy 无流静力参照给出船端张力

$$
\begin{aligned}
T_f^{\mathrm{model}}&=923.615548396\ \mathrm N,\\
T_f^{\mathrm{MoorPy}}&=865.83636483\ \mathrm N,
\end{aligned}
\tag{62}
$$

以及犁侧输出和静力参照

$$
\begin{aligned}
T_{\mathrm{tdp}}^{\mathrm{model}}&=141.469319841\ \mathrm N,\\
T_{\mathrm{in}}^{\mathrm{model}}=T_{\mathrm{adj}}^{\mathrm{model}}&=221.694748912\ \mathrm N,\\
T_p^{\mathrm{MoorPy}}&=18.5202228317\ \mathrm N.
\end{aligned}
\tag{63}
$$

式 (58)--(63) 表明，首帧固定端静力反力与闭式悬链线及 MoorPy 静力定义一致。

末帧船端差异主要来源为动态历史、接触模型和端点约束反力定义。犁侧 \(T_{\mathrm{tdp}}\)、\(T_{\mathrm{in}}\) 与 MoorPy 犁端静力值的差异首先属于输出口径差异；直接比较需采用式 (55a) 的同物理定义条件。

式 (58)--(63) 的首帧结果来自数据集 B，末帧结果来自数据集 A。

## 13. 适用条件

本模型适用于船端位置、犁端位置、放缆速度、海流、材料参数和海床高程均可给定的实时或准实时铺缆张力计算。

埋设犁被处理为给定轨迹的缆线入口边界。犁内滑移、导缆槽摩擦、犁土反力闭合和土体破坏过程由扩展模型处理。

将犁端结构反力、土体阻力或导缆槽摩擦作为验算目标时，应在式 (45)--(50) 之外引入独立的犁-缆-土耦合方程。

模型不通过经验匹配项强制贴合外部软件结果。

若与外部静力或动力工具存在差异，应优先检查理论假设、物理输入、单位、坐标方向、边界条件、离散密度、接触模型、阻尼模型、动态历史窗口和输出物理量定义。
