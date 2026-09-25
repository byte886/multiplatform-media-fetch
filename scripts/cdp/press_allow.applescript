-- press_allow.applescript
-- 作用：在 macOS「辅助功能」权限下，点掉 Google Chrome「要允许远程调试吗？」原生弹窗里的「允许」，
--       并在「点中允许的同一时刻」立刻把前台焦点还给连接前用户正在用的 App。
--
-- 【为什么要还焦】
--   官方授权 sheet 无法永久关闭，且它一出现 macOS 就会自动把 Google Chrome 置前、抢走用户正在
--   打字的 App（如豆包）焦点。本脚本由代点循环每 ~800ms 调一次：点中「允许」后若不还焦，焦点会
--   一直停在 Chrome（直到整个采集 ~28s 结束才由外层兜底归还，太慢）。因此在点中瞬间就地还焦，
--   用户只感知到 Chrome 一闪。原前台 App 名通过命令行第 1 个参数 argv 传入（由 connect_browser 在
--   连接前 captureFrontmost 记录）。
--
-- 【性能关键 · 血泪教训】
--   绝不能递归遍历整个 Chrome 窗口的 AX 树：网页内容区(AXWebArea)有成千上万节点，每个节点都是一次
--   跨进程 AppleEvent 往返，整树遍历在系统繁忙时可达 9 秒以上，会被调用方超时杀掉，表现为
--   「授权窗永远点不中、时好时坏」。而授权弹窗只是挂在 window 上的一个模态 sheet，内部只有寥寥几个按钮。
--   因此本脚本：入口只取 sheets of windows；优先直接取 sheet 的 buttons；兜底也只在 sheet 内部有限深度
--   递归，且遇到 AXWebArea 立即跳过、递归深度封顶。正常耗时稳定在毫秒级。
--
-- 其它已验证事实：
--   - 合成坐标点击只会关窗、不会真正授权；必须对按钮元素 perform action "AXPress"（元素级动作，
--     与屏幕坐标 / 多显示器 / Retina 完全无关，多屏下同样可靠）；
--   - 按钮可见文字在 AXDescription（依次为「在'设置'中关闭 / 取消 / 允许」），AXTitle 为空；
--   - 点中后 sheet 立即关闭，因此「点中即停」，且全程容错：无弹窗 / 进程未就绪 / 元素中途失效，
--     都安静返回 pressed=false 且退出码为 0，可被高频安全重复调用。
--   - 还焦必须走 System Events 的 `set frontmost of process ...`；`tell application X to activate`
--     在被 node 派生的 osascript 宿主下会被系统静默丢弃、不真正前置。
--
-- 前置：运行它的宿主需在「系统设置 → 隐私与安全性 → 辅助功能」中授权。
-- 用法：osascript press_allow.applescript "<连接前前台App名>"

global gPressed

-- 在「很小的一棵子树」（授权 sheet）内找「允许」按钮并 AXPress；绝不进入网页区
on findAllow(el, depth)
	global gPressed
	if gPressed then return
	tell application "System Events"
		try
			set r to role of el
		on error
			return
		end try
		if r is "AXWebArea" then return -- 网页内容区：节点海量，是慢的根源，绝不进入
		if depth > 12 then return
		if r is "AXButton" then
			set d to ""
			try
				set d to (description of el) as string
			end try
			if d contains "允许" then
				try
					perform action "AXPress" of el
					set gPressed to true
				end try
				return
			end if
		end if
		try
			repeat with c in UI elements of el
				my findAllow(c, depth + 1)
				if gPressed then exit repeat
			end repeat
		end try
	end tell
end findAllow

on run argv
	set gPressed to false
	-- 连接前前台 App 名（要还焦的目标）；缺省为空 = 不还焦
	set restoreTo to ""
	if (count of argv) is greater than 0 then
		try
			set restoreTo to (item 1 of argv) as string
		end try
	end if

	set report to ""
	tell application "System Events"
		if not (exists process "Google Chrome") then
			return "pressed=false" & linefeed
		end if
		try
			tell process "Google Chrome"
				repeat with w in windows
					try
						repeat with sh in sheets of w
							-- 最快路径：按钮直接挂在 sheet 上
							try
								repeat with b in buttons of sh
									set dd to ""
									try
										set dd to (description of b) as string
									end try
									set report to report & "BTN-D[" & dd & "] "
									if dd contains "允许" then
										perform action "AXPress" of b
										set gPressed to true
									end if
								end repeat
							end try
							-- 兜底：按钮若被 group/分裂层包裹，只在这棵很小的 sheet 子树内有限递归
							if not gPressed then my findAllow(sh, 0)
						end repeat
					end try
				end repeat
			end tell
		end try
	end tell

	-- 点中「允许」后立刻还焦：仅当本次确实点中、且当前前台仍是 Google Chrome（证明确实是被授权框抢走）、
	-- 且要还回的不是 Chrome 本身时才动作；用户中途自己切走（前台已不是 Chrome）则尊重、不强切。
	if gPressed and restoreTo is not "" and restoreTo is not "Google Chrome" then
		tell application "System Events"
			try
				set curName to name of first process whose frontmost is true
				if curName is "Google Chrome" then
					set frontmost of (first process whose name is restoreTo) to true
				end if
			end try
		end tell
	end if

	return "pressed=" & (gPressed as string) & linefeed & report
end run
