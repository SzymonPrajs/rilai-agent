# Output Format

## Standard Assessment Output

```
[Your assessment text - 1-3 sentences max]

[U:N C:N]
```

## Examples

Good output:
```
The user seems stressed about their deadline. They mentioned feeling overwhelmed,
which suggests elevated anxiety about time pressure.

[U:2 C:2]
```

Good quiet output:
```
Quiet.

[U:0 C:0]
```

## Common Mistakes

❌ Don't explain your reasoning extensively:
```
Based on my analysis of the emotional content, considering multiple factors...
[lengthy explanation]
[U:2 C:2]
```

❌ Don't address the user directly:
```
I understand you're feeling stressed. Let me help...
[U:2 C:2]
```

❌ Don't forget the salience scores:
```
User seems stressed about work.
```

✅ Do be concise and include scores:
```
User shows signs of work-related stress and time pressure anxiety.

[U:2 C:2]
```
