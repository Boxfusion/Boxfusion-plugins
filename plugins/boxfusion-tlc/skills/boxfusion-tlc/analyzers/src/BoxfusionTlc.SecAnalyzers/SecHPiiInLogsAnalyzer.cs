using System.Collections.Immutable;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;

namespace BoxfusionTlc.SecAnalyzers
{
    /// <summary>
    /// SEC-H — personal data (POPIA) interpolated as a value into a log/trace call.
    ///
    /// PREDICATE (operating-standard.md §2): a logging call is passed an interpolated /
    /// concatenated string argument containing a member access <c>X.P</c> where P is a
    /// frozen POPIA token AND the semantic type of the receiver X is a resolvable,
    /// NON-reflection type. The receiver-type resolution is the whole point: it separates
    /// <c>person.FullName</c> (PII) from <c>customSubmitType.FullName</c>
    /// (<see cref="System.Type"/>.FullName, reflection) — the collision a grep cannot
    /// resolve (checks/security.md R8 pin). One finding per enclosing method.
    /// </summary>
    [DiagnosticAnalyzer(LanguageNames.CSharp)]
    public sealed class SecHPiiInLogsAnalyzer : DiagnosticAnalyzer
    {
        // Roslyn requires a DiagnosticId that is a valid identifier (no hyphen); the driver
        // maps '_' → '-' to recover the operating-standard check id "SEC-H".
        public const string Id = "SEC_H";

        private static readonly DiagnosticDescriptor Rule = new DiagnosticDescriptor(
            id: Id,
            title: "Personal data (POPIA) value interpolated into a log/trace call",
            messageFormat: "'{0}' logs the value of PII property '{1}' on a '{2}' receiver",
            category: "Security",
            defaultSeverity: DiagnosticSeverity.Warning,
            isEnabledByDefault: true,
            description: "Log ids/counts, never POPIA values. Receiver type resolved by the semantic model to exclude System.Type.FullName reflection.");

        public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics => ImmutableArray.Create(Rule);

        public override void Initialize(AnalysisContext context)
        {
            context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
            context.EnableConcurrentExecution();
            context.RegisterSyntaxNodeAction(AnalyzeInvocation, SyntaxKind.InvocationExpression);
        }

        private static void AnalyzeInvocation(SyntaxNodeAnalysisContext ctx)
        {
            var inv = (InvocationExpressionSyntax)ctx.Node;
            var model = ctx.SemanticModel;

            if (!IsLogCall(inv, model)) return;

            foreach (var arg in inv.ArgumentList.Arguments)
            {
                var expr = arg.Expression;
                // value-carrying string: interpolation or string concat
                var pii = FindPiiInValueString(expr, model);
                if (pii.node == null) continue;

                var method = AnchorHelper.EnclosingMethod(inv, model);
                if (method == null) return;

                var props = ImmutableDictionary<string, string?>.Empty
                    .Add(AnchorHelper.AnchorKey, AnchorHelper.MemberFragment(method))
                    .Add(AnchorHelper.PathKey, inv.SyntaxTree.FilePath);

                ctx.ReportDiagnostic(Diagnostic.Create(
                    Rule, pii.node.GetLocation(), props,
                    method.ContainingType.Name + "." + method.Name, pii.name, pii.ownerType));
                return; // one finding per enclosing method; stop at the first qualifying site
            }
        }

        private static bool IsLogCall(InvocationExpressionSyntax inv, SemanticModel model)
        {
            string? methodName;
            ExpressionSyntax? receiver = null;
            switch (inv.Expression)
            {
                case MemberAccessExpressionSyntax ma:
                    methodName = ma.Name.Identifier.ValueText;
                    receiver = ma.Expression;
                    break;
                case IdentifierNameSyntax id: // bare call, e.g. LogInfo(...)
                    methodName = id.Identifier.ValueText;
                    break;
                default:
                    return false;
            }
            if (methodName == null || !Predicates.LogMethodNames.Contains(methodName)) return false;

            if (receiver == null)
            {
                // bare call: accept Log*-named wrappers, or a resolved method on a logger type.
                if (methodName.StartsWith("Log")) return true;
                if (model.GetSymbolInfo(inv).Symbol is IMethodSymbol ms && IsLoggerType(ms.ContainingType)) return true;
                return false;
            }

            // identifier receiver name fallback (logger/_logger/Logger/Log)
            var last = LastName(receiver);
            if (last != null && Predicates.LoggerReceiverNames.Contains(last)) return true;

            // semantic receiver type is an ILogger-ish type
            var rt = model.GetTypeInfo(receiver).Type;
            return rt != null && IsLoggerType(rt);
        }

        private static bool IsLoggerType(ITypeSymbol? t)
        {
            if (t == null) return false;
            if (LooksLikeLogger(t)) return true;
            foreach (var i in t.AllInterfaces)
                if (LooksLikeLogger(i)) return true;
            for (var b = t.BaseType; b != null; b = b.BaseType)
                if (LooksLikeLogger(b)) return true;
            return false;
        }

        private static bool LooksLikeLogger(ITypeSymbol t)
        {
            var n = t.Name;
            return n == "ILogger" || n == "ILog" || n == "ILogger`1" || n.EndsWith("Logger");
        }

        /// <summary>
        /// Looks inside an interpolation or string-concat for a PII property access (plain
        /// <c>x.P</c> OR conditional <c>x?.P</c>) whose RESOLVED property symbol is declared
        /// on a non-reflection type. Resolving the property's declaring type — not the raw
        /// text — is what splits <c>person.FullName</c> (declared on an entity, PII) from
        /// <c>customType.FullName</c> (declared on <see cref="System.Type"/>, reflection).
        /// </summary>
        private static (SyntaxNode? node, string? name, string? ownerType)
            FindPiiInValueString(ExpressionSyntax expr, SemanticModel model)
        {
            bool isValueString = expr is InterpolatedStringExpressionSyntax ||
                                 (expr is BinaryExpressionSyntax b && b.IsKind(SyntaxKind.AddExpression) && ContainsString(b, model));
            if (!isValueString) return (null, null, null);

            foreach (var node in expr.DescendantNodes())
            {
                SimpleNameSyntax? nameNode = node switch
                {
                    MemberAccessExpressionSyntax ma => ma.Name,       // x.FullName
                    MemberBindingExpressionSyntax mb => mb.Name,      // x?.FullName
                    _ => null,
                };
                if (nameNode == null) continue;
                if (!Predicates.PiiPropertyTokens.Contains(nameNode.Identifier.ValueText)) continue;

                var sym = model.GetSymbolInfo(node).Symbol;
                if (sym is not IPropertySymbol && sym is not IFieldSymbol) continue; // must be a data member, not a method/type
                var owner = sym.ContainingType;
                if (owner == null) continue;                 // unresolved → skip (conservative, deterministic)
                if (IsReflectionType(owner)) continue;       // System.Type.FullName / System.Reflection.* — benign

                return (node, nameNode.Identifier.ValueText, owner.Name);
            }
            return (null, null, null);
        }

        private static bool ContainsString(ExpressionSyntax e, SemanticModel model)
        {
            foreach (var n in e.DescendantNodesAndSelf())
            {
                if (n is LiteralExpressionSyntax lit && lit.IsKind(SyntaxKind.StringLiteralExpression)) return true;
                if (n is InterpolatedStringExpressionSyntax) return true;
            }
            return false;
        }

        /// <summary>True for the System.Type / System.Reflection metadata family.</summary>
        private static bool IsReflectionType(ITypeSymbol t)
        {
            for (var cur = t; cur != null; cur = cur.BaseType)
            {
                var full = cur.ContainingNamespace?.ToString() ?? "";
                var name = cur.Name;
                if (name == "Type" && full == "System") return true;
                if (name == "RuntimeType" && full == "System") return true;
                if (full == "System.Reflection") return true;      // MemberInfo, MethodInfo, Assembly, AssemblyName, TypeInfo…
                if (full.StartsWith("System.Reflection.")) return true;
            }
            return false;
        }

        private static string? LastName(ExpressionSyntax e) => e switch
        {
            IdentifierNameSyntax id => id.Identifier.ValueText,
            MemberAccessExpressionSyntax ma => ma.Name.Identifier.ValueText,
            _ => null,
        };
    }
}
