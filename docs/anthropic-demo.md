# Anthropic Agents Demo — Results

## Agent CODE (Sonnet)
**Task**: Write `is_prime(n)` with docstring, tests and error handling

```python
def is_prime(n: int) -> bool:
    """
    Vérifie si un entier est premier.
    Raises: TypeError, ValueError
    """
    if not isinstance(n, int):
        raise TypeError(f"Attendu un entier, reçu {type(n).__name__}")
    if n < 0:
        raise ValueError(f"n doit être >= 0, reçu {n}")
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    return all(n % i != 0 for i in range(3, int(n**0.5) + 1, 2))
```

**Result**: O(sqrt(n)) complexity, proper error handling, 8 test cases. ✅

---

## Agent SECURITY (Opus)
**Task**: Audit this code for vulnerabilities

**Found**:
1. **CRITIQUE — CWE-78**: OS Command Injection via `os.system(f"echo {user_input}")`
2. **ÉLEVÉE — CWE-22**: Path Traversal via `open(f"/data/{filename}")`

**Corrections**: `subprocess.run()` with whitelist + `os.path.realpath()` with prefix check. ✅

---

## Agent I18N (Haiku)
**Task**: Translate 3 phrases to Spanish, Portuguese, Arabic

| Original | Espagnol | Portugais | Arabe |
|---|---|---|---|
| Welcome to the multi-agent system | Bienvenido al sistema multiagente | Bem-vindo ao sistema multi-agente | أهلا وسهلا بك في نظام متعدد الوكلاء |
| 9 agents are ready to collaborate | 9 agentes están listos para colaborar | 9 agentes estão prontos para colaborar | 9 وكلاء جاهزون للتعاون |
| Security audit completed successfully | Auditoría de seguridad completada exitosamente | Auditoria de segurança concluída com sucesso | اكتمل تدقيق الأمان بنجاح |

**Result**: 3 languages, professional quality. ✅
