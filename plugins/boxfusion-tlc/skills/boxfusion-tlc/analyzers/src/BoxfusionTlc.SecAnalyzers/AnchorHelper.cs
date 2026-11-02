using System;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace BoxfusionTlc.SecAnalyzers
{
    /// <summary>
    /// Builds the <c>#Type.Member</c> fragment of a §3 stable anchor from a method
    /// symbol, with an overload discriminator <c>(argTypeList)</c> when the containing
    /// type has more than one member of that name (operating-standard.md §3 anchor pins).
    /// The repo-relative, lower-cased path part is prepended by the driver, which knows
    /// the repo root. Pure — no state, no line numbers.
    /// </summary>
    public static class AnchorHelper
    {
        public const string AnchorKey = "anchor_fragment"; // "#Type.Member" (+ optional overload)
        public const string PathKey = "file_path";         // absolute path of the syntax tree

        /// <summary>The <c>#Type.Member</c> (or <c>#Type.Member(argTypes)</c>) fragment.</summary>
        internal static string MemberFragment(IMethodSymbol method)
        {
            var type = method.ContainingType;
            string typeName = type.Name;
            string memberName = method.Name;

            bool overloaded = type.GetMembers(memberName).OfType<IMethodSymbol>().Count() > 1;
            if (!overloaded)
                return "#" + typeName + "." + memberName;

            var args = string.Join(",", method.Parameters.Select(p => SimpleTypeName(p.Type)));
            return "#" + typeName + "." + memberName + "(" + args + ")";
        }

        /// <summary>Minimal, deterministic type name for an overload discriminator.</summary>
        private static string SimpleTypeName(ITypeSymbol t)
        {
            if (t is INamedTypeSymbol named && named.IsGenericType)
            {
                var inner = string.Join(",", named.TypeArguments.Select(SimpleTypeName));
                return named.Name + "<" + inner + ">";
            }
            return t.Name;
        }

        /// <summary>The nearest enclosing method/accessor/local-function symbol of a node.</summary>
        internal static IMethodSymbol? EnclosingMethod(SyntaxNode node, SemanticModel model)
        {
            for (var n = node; n != null; n = n.Parent)
            {
                switch (n)
                {
                    case MethodDeclarationSyntax m:
                        return model.GetDeclaredSymbol(m) as IMethodSymbol;
                    case LocalFunctionStatementSyntax lf:
                        return model.GetDeclaredSymbol(lf) as IMethodSymbol;
                    case AccessorDeclarationSyntax acc:
                        return model.GetDeclaredSymbol(acc) as IMethodSymbol;
                    case ConstructorDeclarationSyntax ctor:
                        return model.GetDeclaredSymbol(ctor) as IMethodSymbol;
                }
            }
            return null;
        }
    }
}
