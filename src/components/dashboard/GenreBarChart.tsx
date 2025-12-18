import { useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Cell,
} from "recharts";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { DashboardStats } from "@/services/system";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface GenreBarChartProps {
  data: DashboardStats["genre_distribution"];
}

const chartConfig = {
  count: {
    label: "Count",
    color: "hsl(var(--primary))",
  },
} satisfies ChartConfig;

const ITEMS_PER_PAGE = 5;

export function GenreBarChart({ data }: GenreBarChartProps) {
  const [currentPage, setCurrentPage] = useState(0);
  
  const totalPages = Math.ceil(data.length / ITEMS_PER_PAGE);
  const startIndex = currentPage * ITEMS_PER_PAGE;
  const paginatedData = data.slice(startIndex, startIndex + ITEMS_PER_PAGE);

  const handlePrev = () => {
    setCurrentPage((prev) => Math.max(0, prev - 1));
  };

  const handleNext = () => {
    setCurrentPage((prev) => Math.min(totalPages - 1, prev + 1));
  };

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-2 shrink-0 flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-lg font-medium">
            Genre Distribution
          </CardTitle>
          <CardDescription>All genres in your library</CardDescription>
        </div>
        <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={handlePrev} disabled={currentPage === 0}>
                <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-xs text-muted-foreground w-12 text-center">
                {currentPage + 1} / {totalPages || 1}
            </span>
            <Button variant="ghost" size="icon" onClick={handleNext} disabled={currentPage >= totalPages - 1}>
                <ChevronRight className="h-4 w-4" />
            </Button>
        </div>
      </CardHeader>
      <CardContent className="flex-1 min-h-0 pl-0 pb-2">
        <ChartContainer config={chartConfig} className="h-full w-full">
          <BarChart
            accessibilityLayer
            data={paginatedData}
            layout="vertical"
            margin={{
              left: 0,
              right: 20,
              top: 10,
              bottom: 10,
            }}
          >
            <CartesianGrid horizontal={false} strokeDasharray="3 3" />
            <YAxis
              dataKey="name"
              type="category"
              tickLine={false}
              tickMargin={10}
              axisLine={false}
              width={120}
              interval={0}
              fontSize={11}
            />
            <XAxis dataKey="count" type="number" hide />
            <ChartTooltip
              cursor={{ fill: "transparent" }}
              content={<ChartTooltipContent hideLabel />}
            />
            <Bar
              dataKey="count"
              layout="vertical"
              radius={[0, 4, 4, 0]}
              barSize={30}
            >
              {paginatedData.map((_entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill="hsl(var(--primary))"
                  fillOpacity={0.8}
                />
              ))}
            </Bar>
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
