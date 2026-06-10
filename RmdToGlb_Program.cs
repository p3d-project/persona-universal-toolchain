using System;
using System.Collections.Generic;
using System.Drawing.Imaging;
using System.IO;

using Assimp;
using AmicitiaLibrary.Graphics.RenderWare;

class Program
{
    static int Main(string[] args)
    {
        if (args.Length < 1)
        {
            Console.WriteLine("Usage: RmdToGlb <input.rmd|rws> [output_dir]");
            return 1;
        }

        string inPath   = Path.GetFullPath(args[0]);
        string outDir   = args.Length >= 2 ? Path.GetFullPath(args[1])
                                           : Path.GetDirectoryName(inPath)!;
        string baseName = Path.GetFileNameWithoutExtension(inPath);

        if (!File.Exists(inPath))
        {
            Console.Error.WriteLine("File not found: " + inPath);
            return 1;
        }

        Directory.CreateDirectory(outDir);
        Console.WriteLine("Loading " + inPath + " ...");

        RmdScene? rmd = null;
        try
        {
            using var fs = File.OpenRead(inPath);
            var magic = new byte[4];
            fs.Read(magic, 0, 4);
            if (magic[0] == 0xF0 && magic[1] == 0xF0 && magic[2] == 0x00 && magic[3] == 0xF0)
            {
                Console.WriteLine("  Detected Atlus P3 FES header, skipping 14 bytes...");
                fs.Seek(14, SeekOrigin.Begin);
            }
            else
            {
                fs.Seek(0, SeekOrigin.Begin);
            }
            rmd = new RmdScene(fs, leaveOpen: false);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("RmdScene parse failed (" + ex.GetType().Name + "): " + ex.Message);
        }

        if (rmd == null || rmd.ClumpCount == 0)
        {
            Console.Error.WriteLine("No clumps found - file may be an RW World (environment) or corrupt.");
            return 1;
        }

        var clump = rmd.Clumps[0];
        Scene aiScene;
        try
        {
            aiScene = RwClumpNode.ToAssimpScene(clump);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ToAssimpScene failed: " + ex.Message);
            return 1;
        }

        int animIdx = 0;
        foreach (var rmdAnim in rmd.Animations)
        {
            try
            {
                RwAnimationNode? rwAnim = null;
                foreach (var node in rmdAnim)
                {
                    if (node is RwAnimationNode an) { rwAnim = an; break; }
                }

                if (rwAnim == null)
                {
                    Console.WriteLine($"  Anim {animIdx}: no RwAnimationNode, skipping.");
                    animIdx++;
                    continue;
                }

                var animScene = RwAnimationNode.ToAssimpScene(rwAnim, clump.FrameList);
                if (animScene.HasAnimations)
                {
                    var aiAnim = animScene.Animations[0];
                    aiAnim.Name = $"Animation_{animIdx:D2}";
                    aiScene.Animations.Add(aiAnim);
                    Console.WriteLine($"  Anim {animIdx}: {aiAnim.NodeAnimationChannels.Count} channel(s), " +
                                      $"dur={aiAnim.DurationInTicks / aiAnim.TicksPerSecond:F2}s");
                }
                else
                {
                    Console.WriteLine($"  Anim {animIdx}: empty after conversion, skipping.");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  Anim {animIdx}: conversion error - {ex.Message}");
            }
            animIdx++;
        }

        Console.WriteLine($"  {animIdx} animation(s) processed, {aiScene.MeshCount} mesh(es), " +
                          $"{aiScene.MaterialCount} material(s).");

        string glbPath = Path.Combine(outDir, baseName + ".glb");

        for (int mi = 0; mi < aiScene.MaterialCount; mi++)
            if (string.IsNullOrEmpty(aiScene.Materials[mi].Name))
                aiScene.Materials[mi].Name = $"Material_{mi}";

        var embeddedIndex = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        string searchDir  = Path.GetDirectoryName(inPath)!;

        foreach (string txdPath in Directory.GetFiles(searchDir, "*.rws"))
        {
            try
            {
                using var txdFs = File.OpenRead(txdPath);

                var peek = new byte[4];
                txdFs.Read(peek, 0, 4);
                txdFs.Seek(0, SeekOrigin.Begin);

                uint chunkId = BitConverter.ToUInt32(peek, 0);
                if (chunkId != 0x00000016)
                {
                    Console.WriteLine($"  [TXD] Skipping {Path.GetFileName(txdPath)} (not a TXD, chunk=0x{chunkId:X8})");
                    continue;
                }

                var txd = new RwTextureDictionaryNode(txdFs, leaveOpen: false);
                Console.WriteLine($"  [TXD] {Path.GetFileName(txdPath)}: {txd.TextureCount} texture(s)");

                foreach (var native in txd.Textures)
                {
                    if (embeddedIndex.ContainsKey(native.Name))
                        continue;

                    using var bmp = native.GetBitmap();
                    using var ms  = new MemoryStream();
                    bmp.Save(ms, ImageFormat.Png);
                    byte[] pngBytes = ms.ToArray();

                    var embedded = new EmbeddedTexture("png", pngBytes);
                    int idx = aiScene.Textures.Count;
                    aiScene.Textures.Add(embedded);
                    embeddedIndex[native.Name] = idx;

                    Console.WriteLine($"    Embedded '{native.Name}'  {native.Width}x{native.Height}  ({pngBytes.Length} bytes)");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  [WARN] TXD load failed for {Path.GetFileName(txdPath)}: {ex.Message}");
            }
        }

        int repointed = 0;
        int notFound  = 0;
        for (int mi = 0; mi < aiScene.MaterialCount; mi++)
        {
            var mat = aiScene.Materials[mi];
            if (!mat.HasTextureDiffuse) continue;

            string texName = Path.GetFileNameWithoutExtension(mat.TextureDiffuse.FilePath);

            if (embeddedIndex.TryGetValue(texName, out int embedIdx))
            {
                var slot = mat.TextureDiffuse;
                mat.TextureDiffuse = new TextureSlot(
                    $"*{embedIdx}",
                    slot.TextureType, slot.TextureIndex,
                    slot.Mapping, slot.UVIndex, slot.BlendFactor,
                    slot.Operation, slot.WrapModeU, slot.WrapModeV, slot.Flags);
                repointed++;
            }
            else
            {
                Console.WriteLine($"  [WARN] No embedded texture found for material '{mat.Name}' -> '{texName}'");
                notFound++;
            }
        }

        if (embeddedIndex.Count > 0)
            Console.WriteLine($"  Textures embedded: {embeddedIndex.Count}, materials repointed: {repointed}, unresolved: {notFound}");
        else
            Console.WriteLine("  [WARN] No TXD found in same folder -- GLB will have no embedded textures.");

        try
        {
            using var ctx = new AssimpContext();
            ctx.SetConfig(new Assimp.Configs.MaxBoneCountConfig(64));
            bool ok = ctx.ExportFile(aiScene, glbPath, "glb2");
            if (!ok)
            {
                Console.Error.WriteLine("AssimpContext.ExportFile returned false.");
                return 1;
            }
            Console.WriteLine("  -> " + glbPath);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("GLB export failed: " + ex.Message);
            return 1;
        }

        return 0;
    }
}
